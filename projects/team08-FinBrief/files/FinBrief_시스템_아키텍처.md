# ARCHITECTURE - FinBrief

## 1. Architecture Goal

FinBrief는 7일 안에 구현 가능한 AI 금융 브리핑 MVP다. 아키텍처의 목표는 매일 아침 배치 파이프라인, 구독 관리, RAG, 카드 생성, 발송, 관측성을 한 흐름으로 연결하는 것이다.

투자 자문, 매매 추천, 자동 주문은 시스템 경계 밖이다.

## 2. System Context

```text
User
  -> Discord Chatbot / Web UI
  -> FastAPI
  -> Supabase(PostgreSQL + pgvector)

Scheduler(08:00)
  -> LangGraph Morning Pipeline
  -> Data APIs(FRED, yfinance, ECOS)
  -> News RSS
  -> LiteLLM(Upstage Solar fallback)
  -> Gemini Image API + matplotlib/PIL
  -> Discord

Observability
  -> Langfuse report/chatbot traces
  -> eval scores
  -> delivery logs
```

## 3. Subsystems

| Subsystem | Responsibility | MVP Boundary |
| --- | --- | --- |
| 관리 챗봇 | 사용자 구독·토픽 CRUD, 티어 확인, 후보 토픽 제안, 리포트 설명, 카드 출처 설명, 기능 외 자연어 LLM 안내 | Discord slash/mention/DM과 persona 기반 응답 |
| 아침 생성·발송 파이프라인 | 뉴스 임베딩, 지표 수집, 리포트 이미지/카드 생성, 결과 저장, 발송 | 매일 08:00 배치와 수동 실행 API |
| 결과 공유 계층 | report run, report explanation, card source explanation 저장/조회 | API, scheduler, bot 프로세스 분리 배포 대응 |
| 데이터 계층 | 사용자, 토픽, 지표, 뉴스 벡터, 카드 캐시, 설명 캐시, 발송 로그 저장 | Supabase 우선, memory repository 테스트 대체 |
| LLMOps 계층 | LiteLLM retry/fallback, guardrail, Langfuse trace/score, 자동 평가 | 실패/비용/품질/챗봇 대화 증거 확보 |

## 4. Layered Structure

```text
app/
  main.py
  api/
    router.py
    routes_health.py
    routes_subscriptions.py
    routes_reports.py
    routes_cards.py
    routes_ingestion.py
  agents/
    graph.py
    nodes.py
    pipeline.py
    report_render.py
    report_ingestion.py
  core/
    config.py
    schemas.py
    llm.py
    llm_guardrails.py
    evaluations.py
    observability.py
    langfuse_scores.py
  repositories/
    protocols.py
    memory.py
    supabase.py
  services/
    chatbot.py
    discord_bot.py
    topic_ingestion.py
    report_result_service.py
    report_explanation_service.py
    card_source_explanation_service.py
    batch.py
    scheduler.py
  tools/
    data_sources/
    embedding/
    news/
frontend/
  index.html
```

## 5. LangGraph Nodes

### A. 관리 챗봇

| Node | Input | Output |
| --- | --- | --- |
| `parse_admin_intent` | user message | intent, slots |
| `resolve_topic` | raw topic text | topic type, source mapping |
| `validate_quota` | user tier, topic count | allowed/blocked |
| `upsert_subscription` | user, topic | saved subscription |
| `list_subscriptions` | user | current topics |
| `delete_subscription` | user, topic | deletion result |
| `explain_report` | user, run_date | report focus explanation |
| `explain_card_sources` | user, run_date, optional topic | card source explanation |
| `unknown_feature_reply` | unsupported natural message | LLM 기반 기능 안내 |
| `format_admin_reply` | tool result | short user reply |
| `suggest_topics` | ambiguous keyword | candidate topics |

### B. 아침 배치 파이프라인

| Node | Input | Output |
| --- | --- | --- |
| `ingest_news` | RSS sources | embedded news rows |
| `collect_indicators` | indicator catalog | today/yesterday values |
| `build_report_page` | indicators, top news | full report |
| `save_report_result` | run summary, report path, snapshots | shared report result |
| `collect_topics` | active subscriptions | unique topic list |
| `load_or_create_card` | topic, date | cached card or generation task |
| `fetch_topic_data` | topic mapping | metric/price data |
| `retrieve_news` | topic, date | RAG evidence |
| `analyze_topic` | data, evidence | structured analysis |
| `generate_image` | topic, analysis | image asset |
| `compose_card` | analysis, image, disclaimer | card artifact |
| `save_card_cache` | card | card URL/id |
| `fanout_delivery` | subscriptions, cards | delivery results |
| `record_trace` | run metadata | Langfuse/eval linkage |

## 6. Data Stores

| Table/Index | Purpose |
| --- | --- |
| `users` | 사용자, tier, channel config |
| `topics` | 토픽 원문, 정규화 이름, 유형, source mapping |
| `subscriptions` | 사용자별 구독 토픽 |
| `indicator_values` | 날짜별 지표 값과 변화율 |
| `news_documents` | 뉴스 원문, 출처, 날짜, 태그 |
| `news_embeddings` | pgvector 임베딩 검색 |
| `cards` | topic+date 카드 캐시 |
| `deliveries` | 채널별 발송 결과와 오류 |
| `eval_runs` | 자동 평가 결과 |
| `report_results` | API/scheduler/bot이 공유하는 report run 결과 |
| `report_explanations` | 당일 리포트 설명 캐시 |
| `card_source_explanations` | topic+date 카드 출처 설명 캐시 |

## 7. Architecture Characteristics

| Characteristic | Fitness Function |
| --- | --- |
| Reliability | 지표 일부 실패 시 나머지 토픽 발송 성공 |
| Accuracy & Safety | 수치 방향 일치, 근거 포함, disclaimer 포함, 투자 조언 금지 |
| Observability | 한 배치 실행과 챗봇 turn마다 Langfuse trace/span/score 연결 |
| Cost Control | 토픽+날짜 캐시로 동일 카드 재생성 방지 |
| Deployability | Docker, GitHub Actions, GCP Compute Engine 수동/스케줄 실행 |

## 8. Key Decisions

- Supabase를 관계형 DB와 pgvector 저장소로 함께 사용한다.
- Discord를 MVP 발송/관리 채널로 구현하고, Slack과 카카오는 추후 delivery adapter로 확장한다.
- 급변동 심층분석 루프는 최종 기획서 기준 MVP에서 제외한다.
- 생성된 카드는 토픽+날짜 단위로 캐싱해 fan-out 비용을 줄인다.
- report 결과와 설명 캐시는 repository 계약으로 저장해 API, scheduler, bot이 같은 결과를 조회한다.
- LLM 호출과 챗봇 대화는 LiteLLM/Langfuse를 통해 trace와 자동 평가를 남긴다.
