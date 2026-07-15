# app/core/ — 공용 기반 코드

여러 계층(api/graph/tools)이 함께 쓰는 설정·연결·인스턴스를 한 곳에서 관리합니다.

| 파일 | 역할 |
|---|---|
| `config.py` | pydantic-settings 기반 전역 설정(`settings`). `.env`를 읽어 API 키·모델명·DB URL 등을 제공. `llm_fallback_model`이 주 모델과 같으면 자동으로 폴백을 비활성화하는 검증 포함 |
| `llm.py` | LLM 인스턴스 중앙 관리 + **주/백업 모델 폴백**. `invoke_with_fallback`(일반 답변용, sync), `ainvoke_structured_with_fallback`(라우터 구조화 출력용, async) — 주 모델(solar-pro3) 실패 시 백업 모델(solar-pro2)로 1회 재시도 |
| `db.py` | Supabase(PostgreSQL) 연결 공용 헬퍼 `get_conn()`. DNS 일시 장애 대비 3회/2초 재시도 포함 — 예전에 tools/ 3개 파일에 복제돼 있던 것을 통합 |
| `tracing.py` | Langfuse 트레이싱 초기화(LLMOps 선택 항목). langfuse 패키지가 없거나(`stretch` 그룹 미설치) 키가 비어있으면 조용히 비활성화 — CI/팀원 환경을 절대 깨지 않음. `get_trace_callbacks()`/`flush_traces()` 제공 |
