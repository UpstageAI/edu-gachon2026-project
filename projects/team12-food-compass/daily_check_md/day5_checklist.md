# Project Day5 (7/14) 체크리스트 — 장바구니 물가 판단 에이전트

> 목표: Day4까지 완성된 배포 인프라(Docker/GCE/CI·CD) 위에서, RAG 기반 대체품 검색·hybrid 경로를 완성하고 참가격 API + 단위환산으로 시나리오 1(쌀 vs 즉석밥)을 완성. RAG 지식검색, LLMOps 안정성 1종 이상, (시간 여유 시) 확장 시나리오 구성까지 진행.
> 완료 기준: 배포된 서버에서 시나리오 2(원물 대체품 판단형)가 실제 ChromaDB 대체품 데이터로 끝까지 동작하고, `main` push → CI 통과 → CD 자동 배포 흐름이 안정적으로 재현됨.
> 참고: 이 체크리스트는 CLAUDE.md §14 로드맵과 이전 세션 dev_notes 기준으로 작성됨 — 항목별 실제 완료 여부가 불확실한 부분은 "확인 필요"로 표시. 진행 상황은 팀원이 직접 채워 넣을 것.

---

## 0. Day4 완료 사항 확인 (이어서 시작하기 전 점검)

- [x] Docker 이미지화(`Dockerfile.api`/`Dockerfile.frontend`/`docker-compose.yml`) — 완료
- [x] GCE VM(`food-compass`, e2-medium, asia-northeast3-c) 생성 및 실제 서버 주소 접속 확인 — 완료
- [x] GitHub Actions CI(`ci.yml`: lint/typecheck/secret-scan/test) — 완료
- [x] GitHub Actions CD(`cd.yml`: GHCR 빌드·Push + Compute Engine Pull 배포, 헬스체크·자동 롤백) — 완료, 첫 실행 성공(7분1초, 병렬 pull로 최적화 진행 중)
- [x] KAMIS 일일 자동 수집(`kamis_daily_fetch.yml`) — 완료
- [ ] `main` 브랜치 branch protection(Require status checks to pass before merging) 설정 — **미완료**, GitHub 웹 UI에서 직접 설정 필요(레포 admin 권한 필요할 수 있음)
- [ ] CD용 GitHub Secrets(`GCE_HOST`/`GCE_USERNAME`/`GCE_SSH_KEY`) 등록 여부 최종 확인
- [ ] 두 번째 이후 배포에서 CD 소요시간이 실제로 줄었는지 재확인 (첫 배포는 이미지 캐시 없어 7분 소요)

---

## 1. RAG 대체품 검색 완성 (hybrid 경로, MVP 핵심)

- [ ] `search_substitute_node`가 모든 품목 카테고리에서 대체품을 정상 반환하는지 재확인
  - **내용**: 이전 세션에 "축산물(소)은 대체품이 나오는데 농산물(상추 등)은 안 나온다"는 이슈가 있었음 — ChromaDB 컬렉션 경로 수정(`docker-compose.yml` volume 경로) 이후 재검증이 필요한 상태. 실제로 해결됐는지, 아니면 여전히 카테고리별 편차가 있는지 확인 필요
  - **Tool**: `compiled_graph.ainvoke()` 직접 호출 또는 배포 서버 `/chat`
  - **참고**: 확실하지 않으니 진행 전 팀원에게 실제 재현 결과 확인할 것

- [ ] RAG 문서(대체 품목 관계) 개수 점검 — CLAUDE.md §10 기준 품목당 2~3개, 총 30~50개 목표
  - **내용**: `data/insertion-chroma-db.py`로 실제 적재된 문서 수와 커버리지(어떤 품목까지 대체품이 있는지) 확인
  - **Tool**: ChromaDB `collection.count()` / `get()`

- [ ] 대체 품목 추천의 "타당성" 정성 확인 (§12 KPI: 평가자가 추가 설명 없이 이해 가능한가)
  - **내용**: 실제 추천 결과가 상식적으로 납득 가능한 대체 관계인지 몇 개 케이스 직접 검토

---

## 2. 참가격 API 연동 + 단위환산 (시나리오 1: 쌀 vs 즉석밥)

- [ ] 참가격(price.go.kr) API 인증키 활성화 여부 확인
  - **내용**: CLAUDE.md §17에 "인증키 활성화 지연 이슈 진행 중"으로 남아있음 — 아직도 막혀 있는지 최신 상태 확인 필요
  - **참고**: 계속 막혀 있으면 시나리오 1 자체를 이번 발표에서 스코프 아웃할지 판단 필요(멘토 문의 후보)

- [ ] `get_processed_price` 구현 (가공식품 소매가 조회)
  - **내용**: `app/tools/price_gokr_client.py` — KAMIS와 동일하게 legacy SSL 컨텍스트 필요 여부 확인

- [ ] `normalize_unit` 구현 (단위 환산)
  - **내용**: `app/tools/normalize.py` — 쌀 kg → 밥 1공기 등, price 경로에 속함(§6.2, hybrid 아님)

- [ ] 시나리오 1 end-to-end 재현: "쌀 사서 밥 짓는 거랑 햇반 사 먹는 거 뭐가 싸?"
  - **Tool**: `compiled_graph.ainvoke()`

---

## 3. RAG 지식검색 완성 (knowledge 경로)

- [ ] `search_knowledge_node`가 실제 ChromaDB 검색을 쓰는지, 아니면 LLM 직접 생성인지 확인
  - **내용**: 현재 코드 확인 결과 `KNOWLEDGE_GENERATION_SYSTEM_PROMPT`로 LLM에 바로 질의하고 있고 `get_collection()` 등 실제 검색 호출은 없어 보임 — "RAG 지식검색"이 로드맵 목표라면 실제 문서 검색(제철정보/보관법 등)을 붙여야 하는지, 아니면 지금 방식(LLM 직접 생성)으로 충분한지 팀 판단 필요
  - **참고**: 확실하지 않은 부분이라 진행 방향은 직접 확인 후 결정할 것

- [ ] RAG 문서(제철정보/보관법·활용팁/가격변동원인) 커버리지 확인
  - **내용**: §10 기준 문서 4종 중 대체품 관계 외 나머지 3종이 실제로 얼마나 채워져 있는지 확인

---

## 4. LLMOps 안정성 1종 이상

- [ ] Langfuse 또는 대체 트레이싱 도구 연동 여부 확인 및 결정
  - **내용**: `pyproject.toml`에 `langfuse` 의존성은 있지만 `app/` 코드에서 실제로 쓰이는 곳은 없음(grep 결과 0건) — 아직 미착수 상태
  - **참고**: §6 기술스택에 "LLMOps: LiteLLM, Auto Router, Langfuse(선택 가점)"로 명시돼 있음 — 남은 일정 대비 투자 가치는 멘토 문의 후보

- [ ] LiteLLM Auto Router(요청 복잡도별 모델 분기) 적용 여부 확인
  - **내용**: 마찬가지로 `pyproject.toml`에 의존성은 있으나 코드에서 미사용 확인됨

---

## 5. 확장 시나리오 구성 (시간 여유 시)

- [ ] 시나리오 3(다인 가구 예산형 장보기) 착수 여부 판단
  - **내용**: `budget_planner` Tool 구현 여부 확인 — 아직 스켈레톤도 없는 것으로 보임
  - **참고**: MVP 4대 기능(§13)에는 포함 안 됨 — 남은 일정(Day6~7) 감안해서 우선순위 판단 필요

- [ ] "사용자 입력 가격 비교" 기능 스코프 결정 (이전 세션에서 논의만 하고 보류된 항목)
  - **내용**: 사용자가 직접 가격을 입력해 주/월/년 전 가격과 비교하는 기능 — 이번 세션에서 스코프를 정하기로 했었음

---

## 6. 문서화 및 발표 준비 (Day6-7 대비 조기 착수)

- [ ] `README.md`에 CD 배포 절차(GHCR 이미지 태그, 롤백 방법 `workflow_dispatch`) 반영
- [ ] 라이브 데모 실패 시 백업 영상 촬영 계획 수립 (§14 Day6 항목 조기 준비)

---

## 진행 체크 (팀 공유용)

| 담당자 | 담당 파트 | 완료 여부 |
|---|---|---|
| | RAG 대체품 검색 완성 | [ ] |
| | 참가격 API + 단위환산 (시나리오 1) | [ ] |
| | RAG 지식검색 완성 | [ ] |
| | LLMOps 안정성 1종 이상 | [ ] |
| | 확장 시나리오 구성 | [ ] |
| | 문서화 | [ ] |

**Day5 완료 기준**: 배포 서버에서 시나리오 2(원물 대체품 판단형)가 실제 ChromaDB 데이터로 정상 동작하고, 시나리오 1(참가격+단위환산)이 최소 한 케이스라도 재현되는 상태로 하루를 마감합니다. 각 항목의 실제 완료 여부는 이 문서 작성 시점 기준 불확실한 부분이 많으므로, 작업 시작 전 팀원 간 현재 상태를 먼저 맞춰볼 것.
