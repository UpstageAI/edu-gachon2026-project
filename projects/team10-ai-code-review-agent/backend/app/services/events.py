"""리뷰 진행 상황을 실시간으로 흘려보내기 위한 인메모리 "이벤트 버스".

리뷰가 돌아가는 동안 단계별 이벤트(대기/시작/완료/실패 등)를 발행(publish)하고,
브라우저가 SSE(Server-Sent Events)로 그 이벤트들을 실시간 구독(stream)한다.
이벤트는 DB가 아니라 프로세스 메모리에만 담아 둔다(가볍고 단순한 대신, 서버를
재시작하면 사라지고 여러 인스턴스 간에 공유되지 않는다).

핵심:
- publish(): 이벤트 하나를 순번(sequence)을 붙여 저장한다.
- stream(): 저장된 이벤트를 순서대로 계속 내보내는 비동기 제너레이터.
- format_sse_event(): 이벤트를 SSE 텍스트 형식으로 바꾼다.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from collections.abc import Callable

from backend.app.core.schemas import JsonDict, ReviewEvent

# 이 이벤트가 나오면 리뷰가 끝난 것이므로 스트림을 닫는다(마지막 이벤트).
TERMINAL_EVENTS = {"review_completed", "review_failed"}


class InMemoryReviewEventBus:
    """리뷰별 이벤트 목록을 메모리에 보관하고 발행/구독을 중개하는 버스."""

    def __init__(self, max_events_per_run: int = 200) -> None:
        # 리뷰 하나당 보관할 최대 이벤트 수(초과분은 오래된 것부터 버린다).
        self.max_events_per_run = max_events_per_run
        # defaultdict(list): 없는 키를 처음 접근하면 빈 리스트를 자동으로 만들어 준다.
        # 구조: {리뷰 ID: [이벤트, 이벤트, ...]}.
        self._events: dict[str, list[ReviewEvent]] = defaultdict(list)
        # RLock: 여러 스레드(백그라운드 리뷰 + 요청 처리)가 동시에 목록을 건드려도
        # 깨지지 않도록 하는 잠금장치. 같은 스레드가 다시 잠글 수 있는(재진입) 종류다.
        self._lock = threading.RLock()

    def publish(
        self,
        review_run_id: str,
        event_type: str,
        payload: JsonDict | None = None,
    ) -> ReviewEvent:
        """이벤트 하나를 만들어 해당 리뷰의 목록에 추가하고 그 이벤트를 돌려준다."""
        # with self._lock: 잠금을 잡고 블록을 벗어나면 자동으로 푼다(동시성 안전).
        with self._lock:
            events = self._events[review_run_id]
            event = ReviewEvent(
                review_run_id=review_run_id,
                sequence=len(events) + 1,  # 순번은 1부터 차례로 매긴다.
                event_type=event_type,
                payload=payload or {},  # payload가 None이면 빈 dict로 둔다.
            )
            events.append(event)
            # 상한을 넘으면 앞쪽(오래된) 이벤트를 잘라내 메모리 사용을 제한한다.
            if len(events) > self.max_events_per_run:
                del events[: len(events) - self.max_events_per_run]
            return event

    def publisher(self, review_run_id: str) -> Callable[[str, JsonDict | None], ReviewEvent]:
        """특정 리뷰 ID에 미리 묶인 발행 함수를 만들어 준다(클로저).

        오케스트레이터 등 리뷰 로직에는 review_run_id를 매번 넘길 필요 없이 이
        publish(event_type, payload)만 건네주면 되도록 감싼 것이다.
        """
        def publish(event_type: str, payload: JsonDict | None = None) -> ReviewEvent:
            return self.publish(review_run_id, event_type, payload)

        return publish

    def snapshot(self, review_run_id: str, after_sequence: int = 0) -> list[ReviewEvent]:
        """주어진 순번 이후의 이벤트들만 복사해 돌려준다(재접속 이어받기에 사용)."""
        with self._lock:
            return [
                event
                for event in self._events.get(review_run_id, [])
                if event.sequence > after_sequence
            ]

    def has_run(self, review_run_id: str) -> bool:
        """이 리뷰 ID에 대한 이벤트가 하나라도 존재하는지 여부."""
        with self._lock:
            return review_run_id in self._events

    async def stream(
        self,
        review_run_id: str,
        after_sequence: int = 0,
        poll_interval_seconds: float = 0.25,
        heartbeat_seconds: float = 15.0,
    ):
        """새 이벤트를 폴링하며 SSE 텍스트로 계속 내보내는 비동기 제너레이터.

        async + yield: 값을 하나씩 흘려보내며, 기다릴 때는 다른 요청에 CPU를 양보한다.
        after_sequence: 이 순번까지는 이미 받았으니 그 다음부터 보내 달라는 뜻.
        종료 이벤트(TERMINAL_EVENTS)를 내보내면 스트림을 닫는다.
        """
        next_sequence = after_sequence + 1
        last_sent_at = time.monotonic()  # monotonic: 뒤로 안 가는 시계(경과시간 측정용).
        while True:
            # 아직 안 보낸 이벤트가 있는지 확인한다.
            events = self.snapshot(review_run_id, after_sequence=next_sequence - 1)
            if events:
                for event in events:
                    next_sequence = event.sequence + 1
                    last_sent_at = time.monotonic()
                    yield format_sse_event(event)  # 이벤트를 클라이언트로 흘려보낸다.
                    if event.event_type in TERMINAL_EVENTS:
                        return  # 리뷰가 끝났으면 스트림 종료.
            # 보낼 이벤트가 없고 일정 시간이 지나면 연결 유지용 주석 줄을 보낸다.
            elif time.monotonic() - last_sent_at >= heartbeat_seconds:
                last_sent_at = time.monotonic()
                yield ": keepalive\n\n"  # ":"로 시작하는 SSE 주석(프록시 타임아웃 방지).

            # 잠깐 쉬며 다른 작업에 양보한 뒤 다시 새 이벤트를 확인한다.
            await asyncio.sleep(poll_interval_seconds)


def format_sse_event(event: ReviewEvent) -> str:
    """이벤트 하나를 SSE 규격 텍스트로 변환한다.

    SSE 한 덩어리는 "id:/event:/data:" 줄들과 빈 줄로 끝난다. id는 재접속 시
    Last-Event-ID로 되돌아와 "여기 다음부터"를 알려주는 데 쓰인다.
    """
    # ensure_ascii=False: 한글이 \uXXXX로 깨지지 않게 그대로 담는다.
    data = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"
