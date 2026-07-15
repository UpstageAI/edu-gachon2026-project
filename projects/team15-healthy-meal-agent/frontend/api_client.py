from __future__ import annotations

import json
import os
from collections.abc import Iterator

import httpx


API_BASE_URL = os.getenv("HEALTHY_MEAL_API_URL", "http://127.0.0.1:8000").rstrip("/")
CHAT_SYNC_URL = f"{API_BASE_URL}/api/v1/chat/sync"
CHAT_STREAM_URL = f"{API_BASE_URL}/api/v1/chat"

# 브라우저가 '직접' 요청하는 URL(레시피 이미지 프록시 등)에 쓰는 공개 주소.
# API_BASE_URL은 서버-서버 통신용이라 배포 시 도커 내부 이름(http://api:8000)이 될 수 있는데,
# 그건 브라우저가 못 찾는다. 이미지 <img src=...>는 브라우저가 로드하므로 공개 주소가 필요하다.
# 미설정 시 API_BASE_URL로 폴백(로컬 개발에선 둘이 같아 무영향).
PUBLIC_API_BASE_URL = os.getenv("HEALTHY_MEAL_PUBLIC_API_URL", API_BASE_URL).rstrip("/")


def build_agent_payload(api_response: dict) -> dict | None:
    meal_type = api_response.get("meal_type")
    items = api_response.get("items") or []
    nutrition = api_response.get("nutrition")
    if not meal_type and not items and not nutrition:
        return None

    return {
        "meal_plan": {
            "meal_type": meal_type or "추천",
            "items": items,
            "reason": api_response.get("reason", ""),
        },
        "nutrition_total": nutrition,
        "validation_result": {
            "status": api_response.get("status"),
            "warnings": api_response.get("warnings") or [],
        },
        "retry_count": api_response.get("retry_count", 0),
        "intent": api_response.get("intent"),
    }


def stream_recommendation(
    user_text: str,
    allergies: list[str] | None = None,
    thread_id: str | None = None,
) -> Iterator[tuple[str, object]]:
    """SSE로 추천 진행 상황을 실시간 수신한다.

    yield 형태:
      ("progress", "건강 조건을 분석하고 있어요…")  # 단계별 진행 문구
      ("result", (content:str, agent_payload:dict|None))  # 최종 결과 1회
      ("error", "에러 메시지")

    연결 실패 등은 ("error", ...)로 넘겨 호출부(app.py)가 말풍선으로 안내한다.
    """
    payload: dict = {"message": user_text, "profile": {"allergies": allergies or []}}
    if thread_id:
        payload["thread_id"] = thread_id
    try:
        with httpx.stream("POST", CHAT_STREAM_URL, json=payload, timeout=60) as resp:
            resp.raise_for_status()
            event = None
            for line in resp.iter_lines():
                if not line:
                    event = None  # 빈 줄 = 프레임 경계
                    continue
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[len("data:") :].strip())
                    if event == "status":
                        yield ("progress", data.get("message", ""))
                    elif event == "result":
                        content = data.get("final_response") or (
                            "조건을 조금 더 알려주시면 식단을 다시 맞춰볼게요."
                        )
                        yield ("result", (content, build_agent_payload(data)))
                    elif event == "error":
                        yield ("error", data.get("message", "추천 중 오류가 발생했어요."))
    except httpx.ConnectError:
        yield (
            "error",
            "API 서버에 연결할 수 없어요.\n\n"
            "백엔드를 먼저 실행해 주세요: "
            "`uv run uvicorn backend.main:app --reload --port 8000`",
        )
    except Exception as exc:
        yield ("error", f"추천 요청 중 오류가 발생했어요.\n\n```text\n{exc}\n```")


def run_recommendation(
    user_text: str,
    allergies: list[str] | None = None,
    thread_id: str | None = None,
) -> tuple[str, dict | None]:
    """추천 요청. 알레르기(프로필)와 thread_id(멀티턴 대화 식별자)를 함께 전달한다."""
    payload: dict = {
        "message": user_text,
        "profile": {"allergies": allergies or []},
    }
    if thread_id:
        payload["thread_id"] = thread_id
    try:
        response = httpx.post(
            CHAT_SYNC_URL,
            json=payload,
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("final_response") or "조건을 조금 더 알려주시면 식단을 다시 맞춰볼게요."
        return content, build_agent_payload(data)
    except httpx.ConnectError:
        return (
            "API 서버에 연결할 수 없어요.\n\n"
            "백엔드를 먼저 실행해 주세요: `uv run uvicorn backend.main:app --reload --port 8000`\n\n"
            f"요청 URL: `{CHAT_SYNC_URL}`",
            None,
        )
    except httpx.HTTPStatusError as exc:
        return (
            "API가 오류 응답을 반환했어요.\n\n"
            f"상태 코드: `{exc.response.status_code}`\n\n"
            f"응답: `{exc.response.text[:500]}`",
            None,
        )
    except Exception as exc:
        return (
            f"API 요청을 처리하는 중 오류가 발생했어요.\n\n```text\n{exc}\n```",
            None,
        )
