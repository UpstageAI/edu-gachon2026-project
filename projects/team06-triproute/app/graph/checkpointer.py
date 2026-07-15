# app/graph/checkpointer.py
#
# LangGraph 실행 상태를 Supabase Postgres에 체크포인트로 저장한다. graph.invoke()를
# config={"configurable": {"thread_id": ...}}와 함께 호출하면, 매 노드 실행 직후 State
# 스냅샷이 thread_id 기준으로 자동 저장돼서 같은 thread_id로 다음 턴을 이어서 실행하거나,
# 중간에 프로세스가 죽어도 마지막으로 성공한 노드부터 재개할 수 있다.
#
# app.core.state.previous_condition_summary/previous_result(수동으로 요청/응답에 실어
# 보내는 최종 결과 한 장)와는 다른 층위다 — 이건 그래프 "실행 자체"의 중간 상태를
# LangGraph가 자동으로 기억하는 것이고, 위 둘은 "대화 맥락"을 애플리케이션 코드가 직접
# 기억하는 것이다. 서로 대체 관계가 아니라 같이 쓰일 수 있음.

import time
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.config import settings

_checkpointer: Optional[BaseCheckpointSaver] = None
_pool = None
# 연결을 이미 한 번(재시도까지 다 써서) 실패했으면 다시 시도하지 않는다 — 안 그러면
# 잘못된/접속 불가능한 SUPABASE_DB_URL이 설정된 채로 떠 있는 동안 매 요청마다 몇 초씩
# 재접속을 시도하다 실패하는 지연이 반복된다(프로세스를 재시작하면 다시 시도함).
_connection_failed = False

# DNS 조회가 순간적으로 실패했다가 몇 초 뒤엔 정상으로 돌아오는 경우를 실제로 겪어서
# (같은 호스트가 한 번은 resolve 실패, 바로 다음 시도엔 성공) 첫 시도 실패로 바로
# 포기하지 않고 몇 번 더 시도해본다.
_SETUP_RETRY_ATTEMPTS = 3
_SETUP_RETRY_DELAY_SECONDS = 2


def get_checkpointer() -> Optional[BaseCheckpointSaver]:
    """
    SUPABASE_DB_URL이 설정돼 있으면 Postgres 체크포인터를 만들어(최초 1회) 반환하고,
    없으면 None을 반환한다 — 호출부(workflow.py)가 None이면 체크포인터 없이 그래프를
    컴파일해서, 이 기능을 아직 설정 안 한 환경(로컬 개발/CI)에서도 기존과 동일하게
    동작하게 한다. psycopg/langgraph-checkpoint-postgres import도 이 함수 안에서만
    하므로, SUPABASE_DB_URL을 안 쓰는 환경에선 해당 패키지가 설치 안 돼 있어도 무관하다.
    """
    global _checkpointer, _pool, _connection_failed

    if not settings.SUPABASE_DB_URL or _connection_failed:
        return None

    if _checkpointer is None:
        try:
            from psycopg_pool import ConnectionPool

            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as e:
            # psycopg_pool/langgraph-checkpoint-postgres가 설치 안 된 환경(예: 슬림 Docker
            # 이미지)에서도 이 모듈을 import하는 순간 앱 전체가 죽지 않도록, 위 setup 실패
            # 케이스와 동일하게 경고만 남기고 체크포인트 없이 동작하게 한다.
            print(
                f"[경고] LangGraph 체크포인터 관련 패키지 import 실패, "
                f"체크포인트 없이 실행합니다: {e}"
            )
            _connection_failed = True
            return None

        checkpointer = None
        last_error: Exception | None = None

        for attempt in range(1, _SETUP_RETRY_ATTEMPTS + 1):
            pool = ConnectionPool(
                conninfo=settings.SUPABASE_DB_URL,
                max_size=10,
                timeout=10,
                kwargs={
                    "autocommit": True,
                    # Supabase의 pooler(6543, transaction 모드)는 매 실행이 서로 다른 백엔드
                    # 커넥션으로 라우팅될 수 있어서, psycopg가 준비한 이름 있는 prepared
                    # statement가 다음 실행 때 다른 백엔드에 없거나 이름이 충돌한다
                    # (DuplicatePreparedStatement 에러로 실제 재현됨). None으로 꺼서 매번
                    # 일반 쿼리로만 실행되게 한다.
                    "prepare_threshold": None,
                    "connect_timeout": 5,
                },
            )
            try:
                candidate = PostgresSaver(pool)
                # 최초 1회 필요한 테이블(checkpoints/checkpoint_writes 등)을 생성한다.
                # 이미 있으면 아무 것도 안 하므로 매번 호출해도 안전하다.
                candidate.setup()
                checkpointer = candidate
                break
            except Exception as e:
                last_error = e
                pool.close()
                if attempt < _SETUP_RETRY_ATTEMPTS:
                    print(
                        f"[경고] LangGraph 체크포인터 연결 실패({attempt}/{_SETUP_RETRY_ATTEMPTS}), "
                        f"{_SETUP_RETRY_DELAY_SECONDS}초 뒤 재시도합니다: {e}"
                    )
                    time.sleep(_SETUP_RETRY_DELAY_SECONDS)

        if checkpointer is None:
            # SUPABASE_DB_URL이 잘못됐거나(오타/비밀번호 오류) 네트워크에서 접속이 안 되는
            # 경우(예: Supabase 직접 연결 호스트가 IPv6 전용이라 IPv4만 되는 환경에서 접속
            # 자체가 안 되는 흔한 케이스 — 이땐 pooler 연결 문자열을 대신 써야 함) 여기서
            # 막지 않으면 이 모듈을 import하는 순간(workflow.py 로드 시점) 앱 전체가
            # 죽어버린다. 체크포인트는 있으면 좋은 기능이지 필수 기능이 아니므로, 재시도까지
            # 다 실패하면 경고만 남기고 체크포인트 없이 그냥 동작하게 한다.
            print(
                f"[경고] LangGraph 체크포인터 연결 {_SETUP_RETRY_ATTEMPTS}회 재시도 모두 실패, "
                f"체크포인트 없이 실행합니다: {last_error}"
            )
            _connection_failed = True
            return None

        _pool = pool
        _checkpointer = checkpointer

    return _checkpointer
