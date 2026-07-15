"""학사 정형 데이터 접근 (courses / graduation_requirements)."""

from app import config, db
from app.core.admission import applicable_curriculum_year
from app.core.graduation import load_graduation_records


class AcademicRepository:
    def recommend_courses(self, 학년: int, 학기: int, 트랙: str | None = None) -> list[dict]:
        """해당 학년/학기 개설 과목. 트랙 지정 시 공통+해당트랙만."""
        conn = db.connect()
        try:
            # 개설학년='0'(전체 학년)·개설학기='매학기'로 적재된 과목(AI부트캠프
            # 등)은 특정 학년/학기 정확 일치로만 필터하면 어떤 학기를 물어도 결과에서
            # 빠진다. '0'/'매학기'는 요청 학년/학기와 무관하게 항상 포함한다.
            # (계절학기는 정규 1·2학기 추천과 별개 학기이므로 제외.)
            sql = (
                "SELECT 교과목명, 이수구분, 학점, 트랙 FROM courses "
                "WHERE (개설학년 = %s OR 개설학년 = '0') "
                "AND (개설학기 = %s OR 개설학기 = '매학기')"
            )
            params: list = [str(학년), str(학기)]
            if 트랙:
                sql += " AND 트랙 IN ('공통', %s)"
                params.append(트랙)
            sql += " ORDER BY 이수구분, 교과목명"
            rows = conn.execute(sql, params).fetchall()
            # 개설학년/개설학기를 과목마다 명시한다(응답 LLM이 개별 과목에 엉뚱한
            # 학년/학기를 임의로 붙이는 환각을 막기 위한 근거).
            return [
                {
                    "교과목명": r[0],
                    "이수구분": r[1],
                    "학점": r[2],
                    "트랙": r[3],
                    "개설학년": 학년,
                    "개설학기": 학기,
                }
                for r in rows
            ]
        finally:
            conn.close()

    def _load_by_year(self) -> list[dict]:
        """학번별 졸업요건 리스트(신뢰 원본, 정규화 완료). 구 단일 파일로 폴백해도
        동일 스키마를 보장한다(app.core.graduation)."""
        return load_graduation_records(config.STRUCTURED_DIR)

    def available_graduation_years(self) -> set[int]:
        """졸업요건 데이터를 보유한 교육과정 년도 집합."""
        return {r["교육과정_연도"] for r in self._load_by_year()}

    def get_graduation_requirements(self, admission_year: int | None = None) -> dict:
        """졸업 이수학점 기준(정형 JSON = 신뢰 원본).

        admission_year(학번)를 주면 해당 학번에 적용되는 교육과정 년도로 매핑해
        그 년도의 요건을 반환한다. 없으면(=None) 최신 년도를 반환한다.
        반환 dict에는 매핑 결과를 알리는 '적용_교육과정_연도'를 덧붙인다.
        """
        records = self._load_by_year()
        by_year = {r["교육과정_연도"]: r for r in records}
        years = set(by_year)
        if admission_year is not None:
            applied = applicable_curriculum_year(admission_year, years)
        else:
            applied = max(years)
        req = dict(by_year[applied])
        req["적용_교육과정_연도"] = applied
        return req
