# Team8 FinBrief 프로젝트 기획서 및 7일 개발 로드맵

> 최종 기준 문서: `project_docs/01_최종_제출/8팀_최종_프로젝트_기획서.md`, `project_docs/01_최종_제출/8팀_최종_프로젝트_기획서.docx`

## 1. 주제 추천 및 설정

### 1.1 최종 확정 주제

**FinBrief - 개인 맞춤 AI 금융 브리핑 에이전트**

매일 아침 주요 거시 금융 지표를 수집·분석해 전체 지표 리포트 이미지와 개인 관심 토픽별 카드뉴스를 자동 생성하고, Discord 챗봇/채널로 전달하는 AI 에이전트 서비스다. Slack은 발송 adapter 확장 후보로 남긴다.

### 1.2 최종 선택 이유

| 기준 | 판단 |
| --- | --- |
| 사용자 문제 명확성 | 개인 투자자는 매일 환율, 금리, 유가, 지수, 뉴스를 여러 앱에서 따로 확인한다. |
| 7일 구현 가능성 | 지표 수집, 뉴스 RSS, RAG, 카드 생성, Discord bot/webhook 발송으로 end-to-end MVP를 만들 수 있다. |
| Agentic Workflow | 스케줄러가 수집, 분석, 생성, 캐시, 발송을 자동 수행한다. |
| LLMOps 실증성 | LiteLLM, Langfuse, 자동 평가, 오류 분석을 실제 실행 증거로 남길 수 있다. |
| 발표 설득력 | “아침에 내 관심 금융 카드가 도착한다”는 사용 장면이 직관적이다. |

### 1.3 이전 기획 대비 변경점

| 항목 | 이전 방향 | 최종 방향 |
| --- | --- | --- |
| 서비스명 | 이전 금융 리포트 초안 | FinBrief 확정 |
| 핵심 경험 | 급변동 감지와 심층분석 | 구독 토픽 기반 정시 카드뉴스 |
| MVP 발송 | Slack/Discord 후보 병행 | Discord 중심 시연, Slack/Kakao는 adapter 확장 후보 |
| 데이터 저장 | 리포트 중심 | Supabase 관계형 + pgvector 통합 |
| 분석 흐름 | 급변동 조건부 루프 | 뉴스 RAG + 토픽 카드 생성 |
| 제외 범위 | 불명확 | 급변동 루프, 실제 결제, 카카오 알림톡, 대규모 운영 제외 |

## 2. 문제 정의

개인 투자자와 금융 뉴스 팔로워는 매일 아침 환율, 금리, 유가, 금, 비트코인, 나스닥, S&P, 주요 뉴스를 여러 서비스에서 확인한다. 숫자는 쉽게 볼 수 있지만, “어떤 지표가 움직였고 어떤 뉴스가 함께 언급되는지”를 출근 전 5분 안에 정리하기 어렵다.

FinBrief는 이 반복 확인 비용을 줄이고, 사용자가 구독한 관심 토픽에 맞춰 안전한 참고용 브리핑을 자동 전달한다.

## 3. 대상 사용자와 페르소나

| Persona | 상황 | 필요 |
| --- | --- | --- |
| 30대 직장인 개인 투자자 | 출근길에 시장 분위기만 빠르게 파악하고 싶음 | 관심 지표 중심 카드뉴스 |
| 금융 뉴스 팔로워 | 숫자와 관련 뉴스를 같이 보고 싶음 | 전체 지표 리포트 + 뉴스 근거 |
| 초보 투자자 | 투자 조언과 정보 요약을 구분하기 어려움 | 수치 근거와 disclaimer가 있는 안전한 요약 |

## 4. 핵심 가치 제안

> 매일 아침, 내 관심 지표를 시각화된 카드 한 장으로 자동으로 받아본다.

핵심 가치는 개인화, 정시성, 시각화, 안전성이다. FinBrief는 투자 판단을 대신하지 않고, 사용자가 시장 흐름을 빠르게 이해할 수 있도록 참고용 정보만 제공한다.

## 5. 서비스 범위

### 5.1 MVP 포함 범위

- 관리 챗봇 기반 관심 토픽 추가, 조회, 삭제
- free tier 기본 5개 토픽 제한
- FRED, yfinance, ECOS 기반 지표 수집
- 경제 뉴스 RSS 수집, 임베딩, Supabase pgvector 저장
- 토픽별 RAG 검색과 구조화 요약
- 전체 지표 리포트 이미지 생성
- 토픽별 카드뉴스 생성
- 토픽+날짜 카드 캐싱
- report run, report explanation, card source explanation 저장소 기반 결과 공유
- 당일 리포트 RSS/RAG 설명
- 카드뉴스 출처 설명
- 구독자별 FanOut 발송
- Discord bot/channel 발송
- LiteLLM retry/fallback 및 금융 safety guardrail
- Langfuse report/card/chatbot trace와 자동 평가 score

### 5.2 MVP 제외 범위

- 카카오 알림톡 실제 발송
- 실제 결제와 과금 처리
- 급변동 심층분석 루프
- 대규모 다중 사용자 운영
- 장기 대화 메모리
- 투자 추천, 매매 판단, 자동 주문

## 6. 주요 기능

| 기능 | 설명 | MVP 우선순위 |
| --- | --- | --- |
| 구독 관리 | 관심 토픽 CRUD, tier 제한 | P0 |
| 지표 수집 | 환율, 금리, 유가, 금, 비트코인, 나스닥, S&P | P0 |
| 뉴스 수집/RAG | RSS 수집, 임베딩, 토픽 관련 뉴스 검색 | P0 |
| 전체 리포트 | 주요 지표 전체를 1080x1080 이미지로 생성 | P0 |
| 카드뉴스 | 지표 대시보드, AI 이미지, 관련 뉴스, disclaimer | P0 |
| 카드 캐시 | topic+date 기준 재사용 | P0 |
| 결과 공유 | API, scheduler, Discord bot이 같은 report/card 결과를 조회 | P0 |
| 리포트 설명 | 당일 변동 큰 지표와 RSS/RAG 근거 설명 | P0 |
| 카드 출처 설명 | 카드뉴스 작성에 사용된 뉴스 출처와 링크 설명 | P0 |
| 대화형 챗봇 | persona, 후보 토픽 제안, 기능 외 자연어 LLM 안내 | P0 |
| 개인 발송 | Discord bot/webhook | P0 |
| LLMOps | LiteLLM, Langfuse report/chatbot trace, eval score, 오류 분석 | P0 |
| 카카오 발송 | delivery adapter 확장 | P2 |
| 유료 결제 | tier flag 이후 실제 결제 | P2 |

## 7. End-to-End 파이프라인

```text
구독 설정
  -> 관리 챗봇
  -> resolve_topic
  -> Supabase subscriptions 저장

매일 08:00
  -> ingest_news
  -> collect_indicators
  -> build_report_page
  -> save_report_result
  -> collect_topics
  -> FanOut topic pipeline
      -> fetch_topic_data
      -> retrieve_news
      -> analyze_topic
      -> generate_image
      -> compose_card
      -> save_card_cache
  -> fanout_delivery
  -> Discord
  -> report/card explanation cache
  -> Langfuse trace + eval result + chatbot turn score
```

## 8. 시스템 아키텍처

### 8.1 두 개의 서브시스템

| Subsystem | 역할 |
| --- | --- |
| 관리 챗봇 | 구독·토픽 CRUD, tier 확인, 추천, 리포트 설명, 카드 출처 설명, 기능 외 자연어 LLM 안내 |
| 생성·발송 파이프라인 | 뉴스 임베딩, 지표 수집, 리포트/카드 생성, 캐시, 결과 공유 저장, 발송 |

### 8.2 Layered Architecture

```text
api          FastAPI route
agents       LangGraph workflow
core         schema, safety, LLM gateway, evaluator, observability
repositories Supabase/memory persistence
services     chatbot, ingestion, report explanation, scheduler, delivery orchestration
tools        data API, RSS, embedding, image, delivery adapter
frontend     FastAPI가 서빙하는 데모/결과 확인 화면
```

### 8.3 LangGraph 노드

| Node | 역할 |
| --- | --- |
| `parse_admin_intent` | 구독 관리/리포트 설명/출처 설명/추천/unknown 안내 의도 분류 |
| `resolve_topic` | 토픽 유형과 데이터 소스 매핑 |
| `validate_quota` | free tier 5개 제한 확인 |
| `ingest_news` | 뉴스 수집과 임베딩 저장 |
| `collect_indicators` | 지표 수집과 변화율 계산 |
| `build_report_page` | 전체 지표 리포트 이미지 생성 |
| `save_report_result` | API, scheduler, bot이 공유할 report 결과 저장 |
| `collect_topics` | 활성 구독 토픽 중복 제거 |
| `fetch_topic_data` | 토픽별 지표·가격 데이터 조회 |
| `retrieve_news` | 날짜 필터 + 벡터 유사도 검색 |
| `analyze_topic` | 수치와 뉴스 근거 기반 구조화 요약 |
| `generate_image` | Gemini API와 matplotlib/PIL 기반 이미지 생성 |
| `compose_card` | 카드뉴스 산출물 조합 |
| `save_card_cache` | 토픽+날짜 기준 저장 |
| `fanout_delivery` | 구독자별 Discord 발송 |
| `explain_report` | 저장된 report 결과와 RSS/RAG 근거 기반 당일 해설 생성 |
| `explain_card_sources` | 카드 evidence 또는 RAG 뉴스 기반 출처 설명 생성 |

## 9. 데이터 설계

| 데이터 | 저장 위치 | 설명 |
| --- | --- | --- |
| 사용자 | Supabase PostgreSQL | user_id, tier, channel config |
| 토픽 | Supabase PostgreSQL | name, type, source mapping |
| 구독 | Supabase PostgreSQL | user-topic 관계 |
| 지표 값 | Supabase PostgreSQL | 날짜별 값과 변화율 |
| 뉴스 원문 | Supabase PostgreSQL | title, source, url, published_at |
| 뉴스 임베딩 | Supabase pgvector | 토픽 RAG 검색 |
| 카드 캐시 | Supabase 또는 파일 스토리지 | topic+date 카드 재사용 |
| 리포트 결과 | Supabase PostgreSQL | run_id, run_date, report_url, indicator snapshot, trace_id |
| 리포트 설명 | Supabase PostgreSQL | 당일 리포트 해설 캐시 |
| 카드 출처 설명 | Supabase PostgreSQL | topic+date별 출처 설명 캐시 |
| 발송 로그 | Supabase PostgreSQL | success/failed/retry |
| 평가 결과 | 파일 또는 Supabase | eval score와 오류 유형 |

## 10. 기술 스택

| Area | Stack |
| --- | --- |
| Backend | Python, FastAPI |
| Workflow | LangGraph |
| UI | FastAPI static frontend |
| DB/RAG | Supabase PostgreSQL + pgvector |
| LLM Gateway | LiteLLM |
| LLM Model | Upstage Solar fallback path |
| Observability | Langfuse |
| Image | Google Gemini API, matplotlib, PIL |
| Data | FRED, yfinance, 한국은행 ECOS, 경제 뉴스 RSS |
| Delivery | Discord bot/webhook, Slack adapter 후보 |
| Infra | Docker, GitHub Actions, GCP Compute Engine |
| Scheduler | APScheduler 또는 cron |

## 11. LLMOps 및 자동 평가

### 11.1 LiteLLM

- 모든 LLM 호출은 LiteLLM gateway를 통과한다.
- retry, fallback, timeout, token/cost 추적을 적용한다.
- primary 모델 실패 시 fallback 모델 또는 deterministic template를 사용한다.

### 11.2 Langfuse

- 배치 run_id와 trace_id를 연결한다.
- report/card 생성, RAG, delivery, eval score를 trace/span으로 연결한다.
- Discord 챗봇 turn, intent/topic/tool/reply span을 `finbrief.chatbot.turn`으로 추적한다.
- 실패 노드와 fallback 경로를 관측 가능하게 한다.

### 11.3 자동 평가

평가 파일은 `evals/finbrief_eval_set.jsonl`로 둔다.

| 평가 항목 | 방식 |
| --- | --- |
| 수치 방향 일치 | deterministic rule |
| 토픽 유형 분류 | expected label 비교 |
| 뉴스 근거 포함 | evidence 개수와 출처 검사 |
| disclaimer 포함 | rule check |
| 투자 조언 금지 | 금지어/문장 패턴 검사 |
| 카드 형식 | schema validation |
| 한국어 톤 | LLM-as-a-Judge 보조 평가 |

## 12. 오류 분석 계획

| 오류 유형 | 예시 | 대응 |
| --- | --- | --- |
| 데이터 수집 실패 | ECOS 응답 오류 | 해당 지표 제외 후 발송 |
| 뉴스 부족 | 토픽 관련 뉴스 없음 | 지표 중심 카드와 근거 부족 표시 |
| LLM schema 오류 | JSON 파싱 실패 | structured output 재시도 |
| 이미지 실패 | Gemini API 실패 | 차트-only 카드 fallback |
| webhook 실패 | Discord API/webhook 실패 | 재시도 후 failed row 기록 |
| 안전성 위반 | 투자 추천 표현 | 자동 평가 실패 처리 후 재생성 |

## 13. 7일 개발 로드맵

| Day | 날짜 | 목표 | 산출물 | 완료 기준 |
| --- | --- | --- | --- | --- |
| Day1 | 2026-07-08 | 기획 확정과 문서 동기화 | 최종 기획서, 스펙, 아키텍처, 테스트 계획 | `8팀_최종_프로젝트_기획서.*` 기준 문서 업데이트 |
| Day2 | 2026-07-09 | 프로젝트 구조와 mock MVP | FastAPI/LangGraph scaffold, fixture, 기본 topic API | fixture로 리포트 1개 생성 |
| Day3 | 2026-07-10 | 실제 LLM과 발송 연결 | LiteLLM, Langfuse, Discord text delivery | trace_id와 delivery log 확인 |
| Day4 | 2026-07-13 | 배포 가능 상태 | Docker, GitHub Actions, GCP 배포, scheduler | 배포 URL 또는 dry-run evidence |
| Day5 | 2026-07-14 | RAG와 카드뉴스 | pgvector/RAG, 이미지 생성, 카드 캐시 | 토픽 카드 생성과 캐시 재사용 |
| Day6 | 2026-07-15 | 통합·오류 분석·README | 자동 평가, 실패 케이스, 실행 문서 | 제3자 실행 경로와 safety 위반 0건 |
| Day7 | 2026-07-16 | 발표 최종화 | 발표자료, 데모 스크립트, 백업 자료 | 시연 2회 재현 |

## 14. Day별 구현 상세

### Day2 - Mock MVP

- `app/`, `tests/`, `data/`, `evals/` 구조 생성
- `data/default_topics.json`, `data/indicator_seed.json`, `data/news_seed.jsonl`
- FastAPI health, subscriptions, reports run endpoint
- LangGraph mock morning pipeline
- deterministic report/card text 생성

### Day3 - LLM과 발송

- LiteLLM gateway 구현
- Langfuse trace wrapper
- structured output schema
- Discord delivery adapter
- admin chatbot 기본 명령: 추가, 조회, 삭제

### Day4 - 운영 기반

- Dockerfile, docker-compose
- GitHub Actions build/test
- GCP Compute Engine 배포 절차
- APScheduler 또는 cron dry-run
- `.env.example`과 secret guardrail

### Day5 - RAG와 카드

- Supabase schema와 pgvector 검색
- 뉴스 수집/임베딩
- topic+date 카드 캐시
- Gemini/matplotlib/PIL 이미지 생성
- 카드뉴스 artifact 저장

### Day6 - 검증과 문서

- `evals/finbrief_eval_set.jsonl`
- 수치, safety, evidence 자동 평가
- 오류 분석 리포트
- README 실행 경로
- 데모 리허설 기록

### Day7 - 발표

- 사용자 시나리오 중심 발표자료
- live demo와 backup screenshot
- 아키텍처, LLMOps, 오류 대응 근거 정리

## 15. 성공 지표

| KPI | 목표 |
| --- | --- |
| 자동 발송 성공률 | MVP dry-run 기준 95% 이상 |
| 카드 생성 시간 | 수 분 이내 |
| 카드 캐시 | 동일 topic+date 재생성 방지 |
| safety 위반 | 자동 평가 기준 0건 |
| 팀 내부 피드백 | "출근길에 실제로 읽을 만하다"는 정성 피드백 확보 |

## 16. 최종 제출 산출물

- `project_docs/01_최종_제출/8팀_최종_프로젝트_기획서.md`
- `project_docs/01_최종_제출/8팀_최종_프로젝트_기획서.docx`
- 실행 가능한 FastAPI/LangGraph 코드
- FastAPI static frontend 또는 API demo
- Docker/배포/스케줄 증거
- Langfuse trace 또는 로컬 trace artifact
- 자동 평가 결과
- 오류 분석 기록
- README와 발표자료
