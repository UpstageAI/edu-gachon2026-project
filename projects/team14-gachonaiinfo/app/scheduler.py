"""리마인드 예약 발송 스케줄러 (Phase 2).

APScheduler BackgroundScheduler로 앱 프로세스 안에서 주기적으로 마감된
리마인드를 조회해 Resend로 발송한다. 별도 워커 프로세스 없이 단일 FastAPI
프로세스 안에서 동작하는 가장 단순한 구성이다(멀티 인스턴스로 스케일 아웃하면
같은 예약을 중복 발송할 수 있음 - 운영 단계에서는 워커 분리 또는 락 필요).
"""

import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.repositories.reminders import get_reminder_repository
from app.services.email import send_reminder_email
from app.services.reminder_time import now_kst

logger = logging.getLogger("app.rag")

_CHECK_INTERVAL_SECONDS = 30

_scheduler: BackgroundScheduler | None = None


def _process_due_reminders() -> None:
    repo = get_reminder_repository()
    due = repo.fetch_due(now_kst())
    for r in due:
        result = send_reminder_email(to=r["email"], content=r["content"])
        if result["success"]:
            repo.mark_sent(r["id"])
        else:
            repo.mark_failed(r["id"], result["error"])
        logger.info(
            json.dumps(
                {
                    "stage": "reminder_scheduler",
                    "reminder_id": r["id"],
                    "success": result["success"],
                },
                ensure_ascii=False,
            )
        )


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    _scheduler.add_job(
        _process_due_reminders,
        "interval",
        seconds=_CHECK_INTERVAL_SECONDS,
        id="reminder_check",
    )
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
