"""웹 API 진입점(FastAPI 앱): 바깥세상과 리뷰 파이프라인을 잇는 최상위 층.

여기서 제공하는 HTTP 엔드포인트:
- POST /v1/reviews           : 리뷰 요청을 받아 실행(즉시 or 백그라운드).
- POST /v1/github/webhooks   : GitHub webhook을 받아 PR 리뷰를 자동 실행.
- GET  /v1/reviews/{id}/events : 진행 상황을 SSE로 실시간 스트리밍.
- GET  /v1/reviews           : 저장된 리뷰 목록 조회.
- GET  /v1/reviews/{id}      : 리뷰 하나 조회.
- POST /v1/routing/preview   : 특징만 넣어 어떤 경로가 선택될지 미리 보기.
- POST /v1/repositories/{id}/policies/sync : 정책 문서 색인 갱신.

실제 리뷰 로직은 orchestrator가 담당하고, 이 파일은 요청 검증/인증/응답 조립과
백그라운드 실행, GitHub check run 상태 갱신 같은 "연결" 역할만 한다.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from typing import Any

try:
    # FastAPI가 없으면 앱을 못 띄우므로, 친절한 설치 안내와 함께 실패시킨다.
    from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, status
    from fastapi.responses import StreamingResponse
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError("FastAPI is not installed. Run `pip install -e .` first.") from exc

from backend.app.core.config import Settings
from backend.app.core.routing import select_route
from backend.app.core.schemas import PullRequestFeatures, ReviewRequest
from backend.app.services.events import InMemoryReviewEventBus
from backend.app.services.github_app import (
    GitHubAppClient,
    GitHubWebhookError,
    GitHubWebhookProcessor,
    verify_github_signature,
)
from backend.app.services.orchestrator import create_orchestrator
from backend.app.services.rag import create_policy_index
from backend.app.storage.factory import create_review_store

# 앱이 뜰 때 한 번 만들어 두고 계속 재사용하는 전역 객체들(설정/오케스트레이터/이벤트 버스).
settings = Settings.from_env()
orchestrator = create_orchestrator(settings)
review_events = InMemoryReviewEventBus()
# FastAPI 인스턴스. 아래 @app.get/@app.post 데코레이터가 이 app에 경로를 등록한다.
app = FastAPI(title="AI Code Review Agent", version="0.1.0")
logger = logging.getLogger(__name__)


def _authorize(authorization: str | None) -> None:
    """Authorization 헤더가 설정된 API 토큰과 맞는지 검사한다.

    토큰이 설정돼 있지 않으면 인증을 건너뛴다(로컬/개발용). 틀리면 401을 던진다.
    """
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authorization token",
        )


# @app.get("/healthz"): 이 함수를 GET /healthz 요청 처리기로 등록하는 FastAPI 데코레이터.
@app.get("/healthz")
def healthz() -> dict[str, str]:
    """헬스체크: 저장소(DB/파일)가 살아 있는지 확인해 상태를 돌려준다."""
    try:
        create_review_store(settings).healthcheck()
    except Exception as exc:
        # 저장소가 죽어 있으면 503(서비스 이용 불가)으로 알린다.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{settings.storage_backend} database unavailable: {exc}",
        ) from exc
    return {"status": "ok", "database": settings.storage_backend, "queue": "inline"}


def _result_response(result) -> dict[str, Any]:
    """리뷰 결과 객체를 API 응답용 dict로 요약/변환한다(핵심 필드 + 전체 결과)."""
    return {
        "review_run_id": result.review_run_id,
        "status": result.status,
        "route_name": result.route.name,
        "model_tier": result.route.model_tier,
        "findings_count": len(result.findings),
        "result": result.to_dict(),
    }


def _run_review(review_run_id: str, review_request: ReviewRequest):
    """리뷰 파이프라인을 실행한다. 진행 이벤트는 이 리뷰 ID 전용 발행 함수로 보낸다."""
    return orchestrator.run_review(
        review_request,
        review_run_id=review_run_id,
        event_publisher=review_events.publisher(review_run_id),
    )


def _run_review_background(review_run_id: str, review_request: ReviewRequest) -> None:
    """백그라운드에서 리뷰를 돌린다. 실패해도 예외를 삼키고 로그만 남긴다.

    응답을 이미 돌려준 뒤 뒤에서 실행되므로, 여기서 예외가 새어 나가도
    사용자에게 전달할 곳이 없다. 그래서 로그로만 기록한다.
    """
    try:
        _run_review(review_run_id, review_request)
    except Exception:
        logger.exception("review background task failed", extra={"review_run_id": review_run_id})
        return


def _handle_github_webhook_background(
    event_name: str,
    delivery_id: str,
    payload: dict[str, Any],
) -> None:
    """GitHub webhook을 백그라운드에서 처리한다: PR을 리뷰 요청으로 바꿔 실행한다.

    흐름: webhook payload → review_plan(리뷰할 PR 목록) → 이미 리뷰한 건 건너뛰고,
    남은 것마다 GitHub check run을 "진행 중"으로 만들고 리뷰를 실행한다.
    """
    try:
        github_client = GitHubAppClient(settings)
        # webhook 내용을 해석해 "무엇을 리뷰할지"(요청 목록)를 계획으로 만든다.
        plan = GitHubWebhookProcessor(settings, client=github_client).review_plan(
            event_name,
            delivery_id,
            payload,
        )
        store = create_review_store(settings)
        # 이미 저장된 리뷰들의 중복 방지 키를 집합으로 모아 둔다(빠른 포함 검사용).
        existing_idempotency_keys = {
            str(record.get("idempotency_key", "")) for record in store.list_reviews()
        }
        for review_request in plan.requests:
            # 같은 PR/커밋을 이미 리뷰했으면 다시 하지 않고 넘어간다.
            if review_request.idempotency_key() in existing_idempotency_keys:
                logger.info(
                    "github webhook review skipped because idempotency key already exists",
                    extra={
                        "event_name": event_name,
                        "delivery_id": delivery_id,
                        "idempotency_key": review_request.idempotency_key(),
                    },
                )
                continue
            # 리뷰 시작 전, GitHub PR 화면에 "검사 진행 중" 상태를 먼저 표시한다.
            review_request = _create_pending_github_check(github_client, review_request)
            review_run_id = str(uuid.uuid4())  # 이번 실행을 식별할 무작위 고유 ID.
            review_events.publish(
                review_run_id,
                "review_queued",
                {
                    "source": "github_webhook",
                    "event_name": event_name,
                    "delivery_id": delivery_id,
                    "repository": review_request.repository.full_name,
                    "pull_request_number": review_request.pull_request.number,
                    "review_mode": review_request.review_mode,
                },
            )
            try:
                _run_review(review_run_id, review_request)
            except Exception as exc:
                # 리뷰가 실패하면 실패 이벤트를 발행하고, GitHub check도 실패로 마감한다.
                review_events.publish(
                    review_run_id,
                    "review_failed",
                    {
                        "error_type": type(exc).__name__,
                        "message": _exception_summary(exc),
                    },
                )
                _complete_failed_github_check(github_client, review_request, exc)
                logger.exception(
                    "github webhook review failed",
                    extra={
                        "event_name": event_name,
                        "delivery_id": delivery_id,
                        "review_run_id": review_run_id,
                        "repository": review_request.repository.full_name,
                        "pull_request_number": review_request.pull_request.number,
                    },
                )
    except Exception:
        logger.exception(
            "github webhook background task failed",
            extra={"event_name": event_name, "delivery_id": delivery_id},
        )


def _create_pending_github_check(
    github_client: GitHubAppClient,
    review_request: ReviewRequest,
) -> ReviewRequest:
    """GitHub PR에 "AI 리뷰 진행 중" check run을 만들거나 갱신한다.

    check run이란 GitHub PR 화면에 뜨는 검사 항목이다. 리뷰 시작을 사용자에게
    바로 알리려고 먼저 "in_progress"로 표시한다. 새로 만든 경우 그 check_run_id를
    담은 새 review_request를 돌려준다(뒤에서 완료 처리할 때 이 ID가 필요하므로).
    installation_id가 없으면(로컬 테스트 등) 아무것도 하지 않고 그대로 돌려준다.
    """
    if not review_request.github.installation_id:
        return review_request
    # GitHub App이 그 설치 위치에서 API를 호출할 수 있는 임시 토큰을 발급받는다.
    token = github_client.installation_token(review_request.github.installation_id)
    pending_summary = (
        "사용자 요청으로 심층 리뷰를 실행 중입니다."
        if review_request.review_mode == "deep_quality_review"
        else "AI 코드 리뷰를 실행 중입니다."
    )
    # 이미 check run이 있으면(재실행 등) 새로 만들지 않고 상태만 갱신한다.
    if review_request.github.check_run_id:
        github_client.update_check_run(
            review_request.repository.owner,
            review_request.repository.name,
            review_request.github.check_run_id,
            token,
            {
                "status": "in_progress",
                "started_at": _utc_now_iso(),
                "output": {
                    "title": settings.github_check_run_name,
                    "summary": pending_summary,
                },
            },
        )
        return review_request
    # check run이 없으면 새로 만든다.
    check_run = github_client.create_check_run(
        review_request.repository.owner,
        review_request.repository.name,
        token,
        {
            "name": settings.github_check_run_name,
            "head_sha": review_request.pull_request.head_sha,
            "status": "in_progress",
            "started_at": _utc_now_iso(),
            "output": {
                "title": settings.github_check_run_name,
                "summary": pending_summary,
            },
        },
    )
    # replace(dataclass, 필드=값): 원본을 안 바꾸고 일부만 바꾼 복사본을 만든다.
    # 방금 만든 check_run_id를 채워 넣은 새 review_request를 돌려준다.
    return replace(
        review_request,
        github=replace(review_request.github, check_run_id=str(check_run.get("id", ""))),
    )


def _complete_failed_github_check(
    github_client: GitHubAppClient,
    review_request: ReviewRequest,
    exc: Exception,
) -> None:
    """리뷰 실패 시, 진행 중이던 GitHub check run을 "실패"로 마감한다.

    설치 ID나 check_run_id가 없으면(표시할 대상이 없으면) 그냥 넘어간다.
    마감 자체가 또 실패하더라도 원래 리뷰 실패 흐름을 막지 않도록 예외를 삼킨다.
    """
    if not review_request.github.installation_id or not review_request.github.check_run_id:
        return
    try:
        token = github_client.installation_token(review_request.github.installation_id)
        github_client.update_check_run(
            review_request.repository.owner,
            review_request.repository.name,
            review_request.github.check_run_id,
            token,
            {
                "status": "completed",
                "conclusion": "failure",
                "completed_at": _utc_now_iso(),
                "output": {
                    "title": f"{settings.github_check_run_name} 실패",
                    "summary": (
                        "AI 코드 리뷰 실행 중 오류가 발생했습니다.\n\n"
                        f"- 오류 유형: `{type(exc).__name__}`\n"
                        f"- 오류 내용: {_exception_summary(exc)}"
                    ),
                },
            },
        )
    except Exception:
        logger.exception(
            "failed to update github check run after review failure",
            extra={
                "repository": review_request.repository.full_name,
                "pull_request_number": review_request.pull_request.number,
                "check_run_id": review_request.github.check_run_id,
            },
        )


def _exception_summary(exc: Exception) -> str:
    """예외를 사람이 읽을 한 줄 요약으로 다듬는다(줄바꿈 제거, 최대 800자)."""
    message = str(exc).replace("\n", " ").strip()
    if not message:
        # 메시지가 비어 있으면 예외의 클래스 이름이라도 돌려준다.
        return type(exc).__name__
    return message[:800]


def _utc_now_iso() -> str:
    """현재 시각을 GitHub API가 원하는 UTC ISO8601 문자열(...Z)로 만든다."""
    from datetime import UTC, datetime

    # isoformat()의 "+00:00"을 GitHub 관례인 "Z"로 바꾼다.
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# status_code=202: "요청은 받았고 처리는 뒤에서 진행"이라는 뜻(비동기 실행 기본).
@app.post("/v1/reviews", status_code=status.HTTP_202_ACCEPTED)
async def create_review(
    request: Request,
    # BackgroundTasks: 응답을 돌려준 뒤 실행할 작업을 예약하는 FastAPI 도구.
    background_tasks: BackgroundTasks,
    # Header(...)/Query(...): 요청 헤더/쿼리스트링 값을 이 인자로 자동 주입(의존성 주입).
    authorization: str | None = Header(default=None),
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    """리뷰 요청을 받아 실행한다. wait=true면 끝날 때까지 기다렸다 결과를 준다.

    async def: 비동기 함수. await로 I/O(요청 본문 읽기 등)를 기다리는 동안 서버가
    다른 요청을 처리할 수 있다.
    """
    _authorize(authorization)
    payload = await request.json()  # 요청 본문(JSON)을 dict로 읽는다.
    review_request = ReviewRequest.from_dict(payload)
    review_run_id = str(uuid.uuid4())
    # 목록/스트림 구독자가 있을 수 있으니 "대기 중" 이벤트를 먼저 발행한다.
    review_events.publish(
        review_run_id,
        "review_queued",
        {
            "repository": review_request.repository.full_name,
            "pull_request_number": review_request.pull_request.number,
            "review_mode": review_request.review_mode,
        },
    )
    # wait=true: 동기 실행. 리뷰가 끝날 때까지 기다렸다 완성된 결과를 바로 돌려준다.
    if wait:
        return _result_response(_run_review(review_run_id, review_request))

    # 기본: 백그라운드로 실행하고, 진행/결과를 볼 수 있는 URL들을 즉시 돌려준다.
    background_tasks.add_task(_run_review_background, review_run_id, review_request)
    return {
        "review_run_id": review_run_id,
        "status": "accepted",
        "events_url": f"/v1/reviews/{review_run_id}/events",
        "result_url": f"/v1/reviews/{review_run_id}",
    }


@app.post("/v1/github/webhooks", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    # alias: 실제 헤더 이름은 하이픈이 있어(X-GitHub-Event) 파이썬 인자명과 다르므로 지정.
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """GitHub webhook을 받는 엔드포인트. 서명 검증 후 실제 처리는 백그라운드로 넘긴다.

    GitHub은 응답이 느리면 재전송하므로, 여기서는 검증만 빠르게 하고 202를 즉시 준다.
    """
    payload_body = await request.body()  # 서명 검증은 원본 바이트로 해야 하므로 body를 그대로 읽는다.
    try:
        # 요청이 정말 GitHub에서 온 것인지 HMAC 서명으로 확인한다(위조 방지).
        verify_github_signature(
            payload_body,
            settings.github_webhook_secret,
            x_hub_signature_256,
        )
    except RuntimeError as exc:
        # 서버 쪽 설정(secret 미설정) 문제 → 503.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except GitHubWebhookError as exc:
        # 서명 불일치 등 인증 실패 → 401.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # 서명 검증 뒤에 본문을 JSON으로 파싱하고, 필수 헤더들이 있는지 확인한다.
    try:
        payload = json.loads(payload_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="payload must be object")
    if not x_github_event:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-GitHub-Event is required")
    if not x_github_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-GitHub-Delivery is required",
        )

    # 검증 통과 → 실제 리뷰 실행은 백그라운드로 넘기고 곧바로 접수 응답을 준다.
    background_tasks.add_task(
        _handle_github_webhook_background,
        x_github_event,
        x_github_delivery,
        payload,
    )
    return {
        "status": "accepted",
        "event_name": x_github_event,
        "delivery_id": x_github_delivery,
        "review_mode": settings.github_webhook_review_mode,
    }


@app.get("/v1/reviews/{review_run_id}/events")
async def stream_review_events(
    review_run_id: str,
    authorization: str | None = Header(default=None),
    # Last-Event-ID: 브라우저가 끊겼다 재접속할 때 "여기까지 받았다"를 알려주는 표준 헤더.
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    """리뷰 진행 이벤트를 SSE로 실시간 스트리밍한다(브라우저가 구독)."""
    _authorize(authorization)
    if not review_events.has_run(review_run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review events not found")
    try:
        # 재접속이면 그 순번 이후부터, 처음이면 0(=처음부터)부터 보낸다.
        after_sequence = int(last_event_id or "0")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Last-Event-ID must be an integer",
        ) from exc

    # 이벤트 버스의 비동기 제너레이터를 감싸, SSE 텍스트 조각을 하나씩 흘려보낸다.
    async def event_generator():
        async for chunk in review_events.stream(review_run_id, after_sequence=after_sequence):
            yield chunk

    # StreamingResponse: 응답을 한 번에 다 만들지 않고 제너레이터가 주는 대로 흘려보낸다.
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",  # SSE의 MIME 타입.
        headers={
            # 중간 캐시/프록시가 스트림을 모아두지 않고 즉시 흘려보내게 하는 헤더들.
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/v1/reviews")
def list_reviews(
    authorization: str | None = Header(default=None),
    # Query(ge=1, le=500): limit은 1 이상 500 이하만 허용(FastAPI가 자동 검증).
    limit: int = Query(default=100, ge=1, le=500),
    route_name: str | None = Query(default=None),
    model_tier: str | None = Query(default=None),
) -> dict[str, Any]:
    """저장된 리뷰 목록을 최신순으로 돌려준다(경로/모델로 필터, 개수 제한 가능)."""
    _authorize(authorization)
    store = create_review_store(settings)
    records = store.list_reviews(limit=limit, route_name=route_name, model_tier=model_tier)
    return {"count": len(records), "reviews": records}


# 경로의 {review_run_id} 부분이 함수 인자 review_run_id로 자동 전달된다(경로 파라미터).
@app.get("/v1/reviews/{review_run_id}")
def get_review(
    review_run_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """ID로 리뷰 하나를 조회한다. 없으면 404."""
    _authorize(authorization)
    store = create_review_store(settings)
    record = store.get_review(review_run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review not found")
    return record


@app.post("/v1/routing/preview")
async def routing_preview(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """특징 값만 받아 어떤 리뷰 경로가 선택될지 미리 계산해 보여 준다(모델 호출 없음).

    라우팅 규칙을 실제 리뷰를 돌리지 않고 시험해 볼 수 있는 진단/디버깅용 엔드포인트다.
    """
    _authorize(authorization)
    payload = await request.json()
    # 입력 dict에서 값을 꺼내 타입을 보정하며 PullRequestFeatures를 직접 조립한다.
    features = PullRequestFeatures(
        syntax_status=str(payload.get("syntax_status", "unknown")),
        lint_status=str(payload.get("lint_status", "unknown")),
        test_status=str(payload.get("test_status", "unknown")),
        changed_files_count=int(payload.get("changed_files_count", 0)),
        changed_lines=int(payload.get("changed_lines", 0)),
        risk_files=list(payload.get("risk_files", [])),
        policy_available=bool(payload.get("policy_available", False)),
        router_confidence=float(payload.get("router_confidence", 0.8)),
    )
    # routing.py의 실제 규칙을 그대로 사용해 경로를 고른다.
    route = select_route(features, review_mode=str(payload.get("review_mode", "auto")))
    return {
        "route_name": route.name,
        "model_tier": route.model_tier,
        "use_rag": route.use_rag,
        "router_confidence": route.confidence,
        "reasons": route.reasons,
    }


@app.post("/v1/repositories/{repository_id}/policies/sync")
def sync_policies(
    repository_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """저장소 정책 문서를 다시 색인(RAG 검색 대상 갱신)하고 통계를 돌려준다."""
    _authorize(authorization)
    result = create_policy_index(settings).sync()
    # **result: sync()가 준 dict의 키/값을 이 응답 dict에 그대로 펼쳐 넣는다(언팩).
    return {"repository_id": repository_id, "status": "completed", **result}
