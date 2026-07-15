"""리뷰 결과 저장소를 고르는 팩토리 + 저장소가 갖춰야 할 인터페이스 정의.

저장 방식이 두 가지다: 로컬 JSON 파일(LocalJsonStore)과 Postgres DB
(PostgresReviewStore). 설정값(storage_backend)에 따라 둘 중 하나를 만들어 준다.
나머지 코드는 구체 구현이 아니라 아래 ReviewStore "인터페이스"에만 의존하므로,
저장 방식을 바꿔도 호출부는 그대로다.
"""

from __future__ import annotations

from typing import Protocol

from backend.app.core.config import Settings
from backend.app.core.schemas import ReviewResult
from backend.app.storage.local_store import LocalJsonStore
from backend.app.storage.postgres_store import PostgresReviewStore


# Protocol = "덕 타이핑" 인터페이스. 상속하지 않아도 아래 메서드들만 갖추면
# ReviewStore로 취급된다("이 메서드들만 있으면 OK"). 본문 ... 은 선언만 한다는 표시.
class ReviewStore(Protocol):
    """리뷰 저장소가 반드시 제공해야 하는 4가지 동작의 계약(interface)."""

    def save_review(self, result: ReviewResult) -> None:
        # 리뷰 결과 하나를 저장(있으면 갱신)한다.
        ...

    def get_review(self, review_run_id: str) -> dict[str, object] | None:
        # ID로 리뷰 하나를 조회한다. 없으면 None.
        ...

    def list_reviews(
        self,
        limit: int | None = None,
        route_name: str | None = None,
        model_tier: str | None = None,
    ) -> list[dict[str, object]]:
        # 리뷰 목록을 최신순으로 돌려준다. 경로/모델로 걸러내거나 개수를 제한할 수 있다.
        ...

    def healthcheck(self) -> None:
        # 저장소가 정상 동작하는지 확인한다(문제가 있으면 예외를 던진다).
        ...


def create_review_store(settings: Settings) -> ReviewStore:
    """설정에 맞는 저장소 구현을 하나 만들어 돌려준다."""
    if settings.storage_backend == "postgres":
        # Postgres를 쓰려면 접속 주소(DATABASE_URL)가 반드시 있어야 한다.
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required when STORAGE_BACKEND=postgres")
        return PostgresReviewStore(settings.database_url)
    # 기본값: 로컬 JSON 파일 저장소.
    return LocalJsonStore(settings.review_store_path)
