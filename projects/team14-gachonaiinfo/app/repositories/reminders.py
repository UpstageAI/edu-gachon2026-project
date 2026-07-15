"""이메일 리마인드 예약 데이터 접근 (reminder_requests)."""

from datetime import datetime

from app import db
from app.services.reminder_time import now_kst


class ReminderRepository:
    def create(
        self, email: str, content: str, remind_at: datetime, session_id: str | None = None
    ) -> int:
        conn = db.connect()
        try:
            row = conn.execute(
                """
                INSERT INTO reminder_requests (session_id, email, content, remind_at, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (session_id, email, content, remind_at, now_kst()),
            ).fetchone()
            return row[0]
        finally:
            conn.close()

    def fetch_due(self, now: datetime, limit: int = 50) -> list[dict]:
        """status='pending'이고 remind_at이 지난 항목을 발송 대상으로 조회."""
        conn = db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, email, content
                FROM reminder_requests
                WHERE status = 'pending' AND remind_at <= %s
                ORDER BY remind_at
                LIMIT %s
                """,
                (now, limit),
            ).fetchall()
            return [{"id": r[0], "email": r[1], "content": r[2]} for r in rows]
        finally:
            conn.close()

    def mark_sent(self, reminder_id: int) -> None:
        # 발송 완료 후에는 이메일(PII)이 더 이상 필요 없으므로 즉시 비운다.
        # email은 NOT NULL이라 NULL 대신 빈 문자열로 지운다.
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE reminder_requests SET status = 'sent', sent_at = %s, email = '' WHERE id = %s",
                (now_kst(), reminder_id),
            )
        finally:
            conn.close()

    def mark_failed(self, reminder_id: int, error: str) -> None:
        # 실패한 예약은 재발송 대상이 아니므로(fetch_due가 status='pending'만 조회)
        # 이메일을 보관할 이유가 없다 → 함께 비운다.
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE reminder_requests SET status = 'failed', error = %s, email = '' WHERE id = %s",
                (error, reminder_id),
            )
        finally:
            conn.close()

    def list_by_session(self, session_id: str, limit: int = 100) -> list[dict]:
        """해당 세션이 등록한 리마인드만 조회.

        로그 화면은 세션 단위로 격리한다(전체 공유 = PII 노출 사고). 또한 email은
        아예 SELECT하지 않아 로그 경로로 이메일이 새어나가지 않게 한다.
        """
        conn = db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, content, remind_at, status, created_at, sent_at
                FROM reminder_requests
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "content": r[1],
                    "remind_at": r[2],
                    "status": r[3],
                    "created_at": r[4],
                    "sent_at": r[5],
                }
                for r in rows
            ]
        finally:
            conn.close()


_repo: ReminderRepository | None = None


def get_reminder_repository() -> ReminderRepository:
    global _repo
    if _repo is None:
        _repo = ReminderRepository()
    return _repo
