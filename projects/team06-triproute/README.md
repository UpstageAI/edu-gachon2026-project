# TripRoute

> 여행 도시와 취향을 자연어로 입력하고 이동수단을 선택하면, 공공데이터·이동정보 API·RAG·LLM Agent를 활용해 시간대별 여행 일정표, 동선 메모, 예상 비용을 자동 생성하는 Agentic Workflow 프로젝트입니다.

---

## 1. 프로젝트 소개

TripRoute는 사용자가 여행하고 싶은 도시, 날짜, 기간, 여행 스타일을 자연어로 입력하고 이동수단을 선택하면, 관광지 정보와 이동 정보를 기반으로 현실적인 여행 일정을 자동으로 생성해주는 AI 여행 코스 설계 서비스입니다.

- 한 줄 소개: 여행 조건을 자연어로 말하면 AI Agent가 일정표·동선·예상 비용까지 한 번에 만들어주는 여행 플래너
- 주요 사용자: 짧은 일정으로 효율적인 여행을 원하는 20대 대학생/사회초년생, 여행 계획이 낯선 초보 여행자, 처음 방문하는 지역의 지리 감각이 없는 여행자, 계획 수립이 귀찮은 직장인
- 배경: 여행 계획을 세울 때 관광지를 하나씩 검색하고, 동선을 직접 짜고, 비용을 따로 계산해야 하는 번거로움에서 출발했습니다.
- 최종 결과물 형태: Coordinator / Route Planner / Financial 멀티 에이전트가 LangGraph 위에서 협업하는 FastAPI + Gradio 기반 서비스이며, 로그인 후 대화 세션을 이어가며 일정을 수정할 수 있는 형태로 Docker 컨테이너화되어 GCP Compute Engine(GCE) VM에 배포되어 있습니다.

## 2. 문제 정의

여행 계획을 세울 때 사용자는 다음과 같은 어려움을 겪습니다.

- 관광지를 하나씩 검색해야 해서 시간이 오래 걸림
- 처음 방문하는 지역의 지리적 감각이 부족함
- 어떤 장소를 먼저 방문해야 할지 판단하기 어려움
- 장소 간 이동 시간이 일정에 반영되지 않음
- 여행 스타일과 계절 조건을 함께 고려하기 어려움
- 예상 비용을 따로 계산해야 함

기존 여행 정보 서비스는 관광지 정보 나열이나 단순 추천에 그치는 경우가 많고, 개인 취향에 맞춘 동선·일정·비용을 한 번에 제공하지는 못합니다.

## 3. 문제 해결

TripRoute는 **장소 추천 + 방문 순서 추천 + 시간대별 일정표 + 예상 비용 계산**을 하나의 흐름으로 제공해 위 문제를 해결합니다.

- Coordinator Agent가 자연어 입력을 분석해 도시·날짜·기간·취향·일정 강도·이동수단·인원수를 추출합니다.
- Supabase pgvector 기반 RAG로 사용자 취향과 의미적으로 유사한 관광지를 검색합니다.
- Google Places API로 확보한 평점·리뷰 수를 활용해 관광객에게만 유명한 곳과 로컬이 선호하는 곳을 구분해서 추천합니다.
- Route Planner Agent가 TourAPI 관광지 정보·여행코스 데이터(연관 관광지)·카카오모빌리티 API를 활용해 관광지 후보와 구간별 이동 정보를 계산하고 시간대별 일정표를 구성합니다.
- Financial Agent가 이동수단별 교통비, 입장료, 식비, 숙박비 등 예상 비용을 계산합니다.
- 세 Agent는 LangGraph State를 매개로 간접적으로 연결되어, 역할을 분리하면서도 중간 결과를 재사용할 수 있습니다.
- 로그인한 사용자는 대화 세션이 저장되어, "카페 말고 맛집 위주로 바꿔줘", "3일로 늘려줘" 같은 후속 요청도 이전 일정을 이어받아 처리합니다.

전체 아키텍처, State 설계, RAG 흐름 등 자세한 내용은 [`docs/architecture.md`](docs/architecture.md), [`docs/tech_architecture.md`](docs/tech_architecture.md), [`docs/state_design.md`](docs/state_design.md)를 참고해주세요.

## 4. 핵심 기능

- 회원가입/로그인 (Supabase Auth 기반)
- 로그인 사용자별 대화 세션 저장 및 사이드바 최근 대화 목록 제공
- 자연어 여행 조건 입력 (도시, 날짜, 기간, 취향, 일정 강도) 및 이동수단·인원수 선택
- 한국관광공사 TourAPI 기반 관광지 후보 조회 및 여행코스 데이터 기반 연관 관광지 탐색
- Supabase pgvector 기반 취향 매칭 RAG 검색
- Google Places API 평점·리뷰 수 기반 로컬/유명 장소 구분 필터링
- 카카오모빌리티 API 기반 구간별 거리·이동시간 계산
- 시간대별 여행 일정표 자동 생성 및 동선 메모 제공
- 이동수단별 예상 비용(교통비·식비·입장료·숙박비) 계산
- "맛집 위주로 바꿔줘", "3일로 늘려줘" 같은 멀티턴 후속 요청 처리 (직전 일정 유지한 채 재구성)
- 대중교통 등 추정치 기반 정보에 대한 주의사항 안내
- FastAPI 서버가 API와 Gradio UI(`/ui`)를 한 컨테이너에서 함께 서빙
- GitHub Actions 기반 CI/CD (Ruff 린트·pytest → Docker 이미지 빌드 → GHCR push → GCE VM에 docker compose 배포)

## 5. 데모 영상

- 데모 영상: (준비 중)
- 배포 URL: <http://34.50.22.20:8000/ui>
- 추가 시연 자료: (준비 중)

## 6. 팀원 소개

| 이름 | 역할 | GitHub |
|---|---|---|
| 박범진 | UI, Infra | [@bbbj00](https://github.com/bbbj00) |
| 권현석 | Backend, AI Agent | [@elroy0612](https://github.com/elroy0612) |

## 7. 참고자료 / 발표자료

- 발표자료: (준비 중)
- 실행 계획서: [`docs/project_plan.md`](docs/project_plan.md)
- 참고 문서: [`docs/api_notes.md`](docs/api_notes.md), [`docs/architecture.md`](docs/architecture.md)
- 원본 프로젝트 저장소: <https://github.com/bbbj00/team06-TripRoute>

---
