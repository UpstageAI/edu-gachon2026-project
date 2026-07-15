"""Resend API 기반 이메일 리마인드 (Phase 2: 스케줄러가 예약 시각에 호출).

ADR-007: 이메일 주소는 개인정보이므로 여기서만 다루고, 응답 생성 LLM에는
전달하지 않는다(ToolExecutor가 반환하는 data에는 주소를 담지 않는다).
Resend SDK 예외 메시지에는 (샌드박스 제약 안내 등에서) 이메일 주소가 그대로
섞여 나올 수 있어, 원본 예외는 서버 로그에만 남기고 LLM으로 가는 error는
정형화된 문구로 대체한다.
"""

import json
import logging

import resend

from app import config

resend.api_key = config.RESEND_API_KEY

logger = logging.getLogger("app.rag")

_DISCLAIMER = "\n\n---\n※ 학사 일정은 변경될 수 있으니 공식 학사공지에서 최종 확인해 주세요."


def send_reminder_email(to: str, content: str) -> dict:
    if not config.RESEND_API_KEY:
        return {"success": False, "error": "RESEND_API_KEY가 설정되지 않았습니다."}

    try:
        resend.Emails.send(
            {
                "from": config.RESEND_FROM_EMAIL,
                "to": [to],
                "subject": "[가천이] 학사 일정 리마인드",
                "text": content + _DISCLAIMER,
            }
        )
        return {"success": True}
    except Exception as e:  # noqa: BLE001
        logger.info(
            json.dumps(
                {"stage": "reminder_email", "success": False, "error": str(e)},
                ensure_ascii=False,
            )
        )
        return {"success": False, "error": "이메일 발송에 실패했습니다."}
