"""로컬 JSON 파일 기반 리뷰 저장소(ReviewStore 구현 중 하나).

모든 리뷰 결과를 하나의 JSON 파일(리스트)에 이어 붙여 저장한다. DB 없이도 돌아가는
개발/단일 사용 환경용이다. factory.py가 정의한 ReviewStore 인터페이스를 만족한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.schemas import ReviewResult


class LocalJsonStore:
    """리뷰 결과들을 JSON 파일 하나에 배열로 저장/조회하는 저장소."""

    def __init__(self, path: Path) -> None:
        # 리뷰들이 저장될 JSON 파일 경로.
        self.path = path

    def save_review(self, result: ReviewResult) -> None:
        """리뷰 결과 하나를 파일 끝에 덧붙여 저장한다."""
        # parents=True: 중간 폴더까지 만들고, exist_ok=True: 이미 있어도 에러 안 냄.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 기존 기록 전체를 읽어 새 결과를 덧붙인 뒤 파일 전체를 다시 쓴다.
        records = self._read_records()
        records.append(result.to_dict())
        self.path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_reviews(
        self,
        limit: int | None = None,
        route_name: str | None = None,
        model_tier: str | None = None,
    ) -> list[dict[str, object]]:
        """저장된 리뷰 목록을 최신순으로 돌려준다(선택적으로 필터/개수 제한)."""
        # 저장은 오래된→최신 순이므로, reversed로 뒤집어 최신이 앞에 오게 한다.
        records = list(reversed(self._read_records()))
        # route_name/model_tier가 주어지면 해당 값만 남기는 리스트 컴프리헨션.
        if route_name is not None:
            records = [r for r in records if r.get("route", {}).get("name") == route_name]
        if model_tier is not None:
            records = [r for r in records if r.get("route", {}).get("model_tier") == model_tier]
        # limit이 있으면 앞에서 그만큼만 잘라 준다.
        return records[:limit] if limit is not None else records

    def get_review(self, review_run_id: str) -> dict[str, object] | None:
        """ID가 일치하는 리뷰 하나를 찾아 돌려준다. 없으면 None."""
        for record in self._read_records():
            if record.get("review_run_id") == review_run_id:
                return record
        return None

    def healthcheck(self) -> None:
        """저장 폴더가 존재하도록 보장한다(쓰기 가능 여부를 사실상 확인)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_records(self) -> list[dict[str, object]]:
        """파일에서 리뷰 배열을 읽어 온다. 파일이 없거나 깨졌으면 빈 리스트."""
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 파일이 손상돼 JSON 파싱이 실패해도 프로그램이 죽지 않도록 빈 목록 반환.
            return []
        # 최상위가 배열이 아닌 예상 밖 형식이면 무시하고 빈 목록으로 취급한다.
        return payload if isinstance(payload, list) else []
