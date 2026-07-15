# DATA_FLOW - FinBrief

## 1. Final Source Of Truth

이 문서는 `project_docs/01_최종_제출/8팀_최종_프로젝트_기획서.md`와 `project_docs/01_최종_제출/8팀_최종_프로젝트_기획서.docx`의 확정 내용을 기준으로 한다.

## 2. Subscription Flow

```text
User command
  -> Admin Chatbot
  -> parse_admin_intent
  -> resolve_topic / suggest_topics / unknown_feature_reply
  -> validate_quota
  -> topics / subscriptions tables
  -> format_admin_reply
  -> Langfuse chatbot turn trace
```

### Stored Data

| Data | Example |
| --- | --- |
| user_id | `u_001` |
| tier | `free`, `paid` |
| topic_name | `USD/KRW 환율`, `반도체` |
| topic_type | `indicator`, `keyword`, `sector`, `asset` |
| source_mapping | FRED/yfinance/ECOS/RSS mapping |

free tier는 최대 5개 토픽을 허용한다.

## 3. Morning Batch Flow

```text
Scheduler(08:00) or POST /api/v1/reports/run
  -> ingest_news
      -> RSS fetch
      -> embedding
      -> Supabase pgvector
  -> collect_indicators
      -> FRED / yfinance / ECOS
      -> indicator_values
  -> build_report_page
      -> 전체 지표 리포트 저장
      -> report_results 저장
  -> collect_topics
      -> active subscriptions
      -> duplicate topic removal
  -> FanOut by unique topic
      -> load_or_create_card
      -> fetch_topic_data
      -> retrieve_news
      -> analyze_topic
      -> generate_image
      -> compose_card
      -> save_card_cache
  -> fanout_delivery
      -> Discord
  -> record_trace
      -> Langfuse + eval logs
```

## 4. RAG Flow

```text
news RSS item
  -> normalize(title, source, published_at, url, summary)
  -> embed
  -> news_documents + news_embeddings

topic request
  -> date filter
  -> vector similarity search
  -> top-k evidence
  -> structured analysis prompt
```

RAG 검색은 최신성 보호를 위해 날짜 필터를 우선 적용하고, 이후 토픽 유사도로 상위 뉴스를 고른다.

## 5. Card Cache Flow

```text
topic + date
  -> cards lookup
  -> hit: reuse card_id/card_url
  -> miss: generate image + compose card + save
  -> all subscribers receive same cached card
```

캐시 키는 `topic_id + run_date`다. 동일 토픽을 여러 사용자가 구독해도 카드 생성은 한 번만 수행한다.

## 6. Report Result Sharing Flow

```text
LangGraph pipeline result
  -> report_result_service.save_report_result
  -> memory or Supabase report_results
  -> GET /api/v1/reports/today
  -> GET /api/v1/reports/today/explanation
  -> Discord chatbot "오늘 리포트 설명"
```

이 흐름은 `finbrief-api`, `finbrief-bot`, `finbrief-scheduler`가 Docker Compose에서 서로 다른 프로세스로 실행되어도 같은 report 결과를 조회하기 위한 구조다. 메모리 저장소는 테스트용이고, 운영에서는 Supabase 저장소를 사용한다.

## 7. Report Explanation Flow

```text
report result
  -> select_focus_items(change_abs / change_percent)
  -> topic/tag 기반 RSS/RAG evidence 조회
  -> report_explanation_service cache lookup
  -> miss: build explanation
  -> report_explanations upsert
  -> API 또는 Discord 응답
```

리포트 설명은 투자 판단이 아니라 "오늘 어떤 지표와 뉴스 흐름을 함께 보면 좋은지"를 설명한다. 관련 뉴스가 없으면 수치 중심의 안전한 설명으로 fallback한다.

## 8. Card Source Explanation Flow

```text
user + run_date
  -> subscriptions 조회
  -> cards(topic_id + run_date) 조회
  -> card evidence 우선 사용
  -> evidence 부족 시 news RAG fallback
  -> card_source_explanations cache upsert
  -> GET /api/v1/cards/today/sources 또는 Discord 응답
```

카드뉴스 출처 설명은 카드 작성에 쓰인 뉴스 출처, 제목, URL을 사용자에게 보여주는 투명성 기능이다.

## 9. Delivery Flow

```text
subscription rows
  -> group by user and channel
  -> attach report/card links
  -> Discord adapter
  -> delivery result
  -> deliveries table
```

카카오 알림톡은 MVP 제외다. Slack은 추후 adapter 후보로 남기며, 현재 시연 중심 채널은 Discord다.

## 10. Fallback Flow

| Failure | Data Flow Response |
| --- | --- |
| 지표 일부 실패 | 실패 항목을 `missing_indicators`로 기록하고 나머지 지표로 리포트 생성 |
| 뉴스 수집 실패 | 빈 evidence 또는 최근 캐시 뉴스로 카드 생성, 근거 부족 표시 |
| 이미지 생성 실패 | 텍스트 카드와 matplotlib 차트만 발송 |
| 한 채널 발송 실패 | 해당 delivery row만 failed로 기록하고 다른 채널 발송 유지 |
| LLM timeout | LiteLLM retry/fallback 후 실패 시 안전한 템플릿 요약 사용 |
| 챗봇 미지원 자연어 | 실제 구현 기능 범위 안에서 LLM 안내 응답, 실패 시 고정 도움말 fallback |

## 11. Output Artifacts

| Artifact | Description |
| --- | --- |
| full report | 주요 지표 전체와 주요 뉴스 5개 |
| topic card | 토픽별 시각 카드, 관련 뉴스, disclaimer |
| report explanation | 당일 변동 핵심 지표와 RSS/RAG 근거 설명 |
| card source explanation | 카드뉴스별 참고 기사 출처와 링크 |
| delivery log | 채널별 성공/실패/재시도 |
| Langfuse trace | report/card 노드와 chatbot turn별 latency, token, cost, prompt/output |
| eval result | 수치 방향, 근거, 안전성, 형식 검증 결과 |
