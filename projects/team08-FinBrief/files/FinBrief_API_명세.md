# API_SPEC - FinBrief

## 1. Principles

- API는 7일 MVP 구현에 필요한 최소 기능만 제공한다.
- 모든 생성/발송 응답에는 `run_id` 또는 `trace_id`를 포함한다.
- 금융 산출물에는 항상 "투자 조언이 아닌 참고용" disclaimer를 포함한다.
- 카카오 발송 API는 MVP에서 구현하지 않는다.

## 2. Health

### `GET /api/v1/health`

```json
{
  "status": "ok",
  "service": "finbrief",
  "version": "0.1.0"
}
```

## 3. Topics & Subscriptions

### `GET /api/v1/topics`

구독 가능한 기본 토픽 catalog를 조회한다.

```json
{
  "topics": [
    {
      "topic_id": "topic_btc",
      "name": "비트코인",
      "normalized_name": "btc",
      "type": "asset",
      "source_mapping": []
    }
  ]
}
```

### `POST /api/v1/topics/match`

키워드 또는 쿼리 문장을 관심 토픽과 매칭한다. 각 토픽의 `news_keywords`와 이름을 대소문자 무시 부분 일치로 비교하고, 매칭된 항목 수(`score`) 순으로 정렬한다. 2글자 미만 토큰은 무시한다.

요청:

```json
{
  "query": "AI 반도체",
  "limit": 5
}
```

응답:

```json
{
  "query": "AI 반도체",
  "count": 2,
  "matches": [
    {
      "topic": {
        "topic_id": "topic_semi",
        "name": "반도체",
        "normalized_name": "semi",
        "type": "sector",
        "source_mapping": []
      },
      "score": 2,
      "matched_keywords": ["AI 반도체", "반도체"]
    }
  ]
}
```

### `GET /api/v1/subscriptions/{user_id}`

사용자의 현재 구독 토픽을 조회한다.

```json
{
  "user": {
    "user_id": "u_001",
    "tier": "free",
    "max_topics": 5
  },
  "subscriptions": [
    {
      "subscription_id": "sub_001",
      "user_id": "u_001",
      "topic_id": "topic_btc",
      "channel": "discord",
      "active": true
    }
  ],
  "topics": [
    {
      "topic_id": "topic_btc",
      "name": "비트코인",
      "normalized_name": "btc",
      "type": "asset"
    }
  ]
}
```

### `POST /api/v1/subscriptions/{user_id}/topics`

관심 토픽을 추가한다.

```json
{
  "topic_id": "topic_btc",
  "channel": "discord"
}
```

성공 응답:

```json
{
  "subscription": {
    "subscription_id": "sub_001",
    "user_id": "u_001",
    "topic_id": "topic_btc",
    "channel": "discord",
    "active": true
  }
}
```

quota 초과 응답:

```json
{
  "detail": {
    "code": "TOPIC_LIMIT_EXCEEDED",
    "message": "free tier는 최대 5개 토픽까지 구독할 수 있습니다."
  }
}
```

### `DELETE /api/v1/subscriptions/{user_id}/topics/{topic_id}`

구독 토픽을 삭제한다.

```json
{
  "status": "deleted",
  "topic_id": "topic_btc",
  "removed": true
}
```

## 4. Reports

### `POST /api/v1/reports/run`

아침 배치를 수동 실행한다. 개발·시연용 엔드포인트다.

```json
{
  "run_date": "2026-07-08",
  "dry_run": false,
  "refresh_data": true
}
```

응답:

```json
{
  "run_id": "run_20260708_mock",
  "run_date": "2026-07-08",
  "status": "completed",
  "generated_cards": 3,
  "reused_cards": 2,
  "delivery_results": 4,
  "trace_id": "local_mock_trace_run_20260708_mock",
  "report_url": "app/agents/out_reports/20260708/market_report_20260708.png",
  "disclaimer": "본 브리핑은 투자 조언이 아닌 참고용 정보입니다.",
  "eval_summary": {
    "passed": 5,
    "failed": 0
  },
  "ingestion": {
    "topic_ids": ["topic_btc"],
    "indicator_rows": 1,
    "news_rows": 5,
    "embedding_rows": 5
  },
  "errors": []
}
```

`refresh_data=true`이면 현재 active subscription topic을 기준으로 외부 API/RSS 데이터를 먼저 수집·저장한 뒤 리포트 생성을 실행한다. 운영 Supabase 저장소가 없고 `dry_run=false`이면 저장소 부재 오류를 반환한다.

### `GET /api/v1/reports/today`

오늘의 전체 지표 리포트를 조회한다.

```json
{
  "run_date": "2026-07-08",
  "status": "completed",
  "generated_cards": 3,
  "reused_cards": 2,
  "delivery_results": 4,
  "trace_id": "local_mock_trace_run_20260708_mock",
  "report_url": "app/agents/out_reports/20260708/market_report_20260708.png",
  "disclaimer": "본 브리핑은 투자 조언이 아닌 참고용 정보입니다.",
  "errors": []
}
```

### `GET /api/v1/reports/today/explanation`

오늘의 전체 지표 리포트에서 변동이 큰 지표와 함께 봐야 할 RSS/RAG 뉴스 흐름을 설명한다.

Query:

```text
run_date=2026-07-08
max_focus=3
```

응답:

```json
{
  "run_id": "run_20260708_mock",
  "run_date": "2026-07-08",
  "cached": true,
  "reply": "오늘은 USD/KRW 환율과 나스닥 변동을 함께 보면 좋아요.",
  "focus_items": [
    {
      "indicator_id": "usdkrw",
      "display_name": "USD/KRW 환율",
      "change_text": "+0.91%",
      "evidence": []
    }
  ],
  "disclaimer": "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."
}
```

## 5. Topic Ingestion

### `POST /api/v1/topics/{topic_id}/ingest`

선택한 토픽의 지표/뉴스/RAG 데이터를 외부 API에서 수집해 Supabase에 저장한다.

요청:

```json
{
  "run_date": "2026-07-08",
  "include_indicators": true,
  "include_news": true,
  "include_embeddings": true,
  "dry_run": false
}
```

응답:

```json
{
  "run_date": "2026-07-08",
  "topic_ids": ["topic_btc"],
  "indicator_rows": 1,
  "news_rows": 5,
  "embedding_rows": 5,
  "errors": []
}
```

## 6. Cards

### `GET /api/v1/cards/today?user_id=u_001`

사용자에게 오늘 발송될 카드 목록을 조회한다.

```json
{
  "user_id": "u_001",
  "run_date": "2026-07-08",
  "cards": [
    {
      "card_id": "card_topic_btc_20260708",
      "topic_id": "topic_btc",
      "title": "비트코인 상승",
      "image_url": "app/agents/out/2026-07-08_topic_btc.png",
      "cached": true,
      "disclaimer": "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."
    }
  ]
}
```

### `GET /api/v1/cards/today/sources?user_id=u_001`

사용자가 오늘 받을 카드뉴스가 어떤 뉴스 출처를 근거로 작성됐는지 설명한다.

Query:

```text
user_id=u_001
run_date=2026-07-08
topic_id=topic_btc
max_sources=3
```

응답:

```json
{
  "user_id": "u_001",
  "run_date": "2026-07-08",
  "cards": [
    {
      "card_id": "card_topic_btc_20260708",
      "topic_id": "topic_btc",
      "topic_name": "비트코인",
      "cached": true,
      "source_summary": "비트코인 카드뉴스는 연합뉴스의 관련 기사 1건을 근거로 작성됐습니다.",
      "sources": [
        {
          "source": "연합뉴스",
          "title": "비트코인 관련 기사",
          "url": "https://example.test/news"
        }
      ]
    }
  ],
  "disclaimer": "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."
}
```

## 7. Admin Chatbot

### Discord slash command `/finbrief`

현재 관리 챗봇은 FastAPI route가 아니라 Discord slash command 엔트리포인트로 제공한다.
사용자가 `/finbrief message:<자연어>`를 입력하면 `app.services.discord_bot`이
`app.services.chatbot.handle()`을 호출해 구독 관리 tool을 실행한다.

대표 입력:

```text
/finbrief message: 반도체 토픽 추가해줘
/finbrief message: 내 토픽 보여줘
/finbrief message: 비트코인 취소해줘
/finbrief message: 금리 구독
/finbrief message: 처음인데 뭐 받아보면 좋아?
/finbrief message: 오늘 리포트 설명해줘
/finbrief message: 오늘 카드뉴스 출처 알려줘
/finbrief message: 환율이 왜 움직였어?
```

응답 예시:

```json
{
  "intent": "add_topic",
  "status": "completed",
  "reply": "좋아요. 반도체를 아침 브리핑에 추가해둘게요.\n현재 1/5개 토픽을 구독 중입니다.",
  "topic": "topic_semi"
}
```

대화 UX 정책:

- `브리핑 메이트` persona로 짧고 친숙하게 응답한다.
- `금리`, `환율`처럼 후보가 여러 개인 키워드는 `clarify_topic`으로 후보를 먼저 제시한다.
- `매수`, `매도`, `목표가`, `사야 해?`처럼 투자 판단을 요구하는 메시지는 차단하고 브리핑 구독 예시로 안내한다.
- `오늘 리포트 설명`, `출처`, `근거 기사`, `왜 이렇게 썼어?` 같은 자연어 트리거를 리포트/카드 출처 설명으로 연결한다.
- 구현된 기능으로 분류되지 않는 자연어는 LLM이 실제 지원 기능 범위 안에서 적절한 안내 답변을 생성하고, 실패 시 고정 도움말로 fallback한다.
- Discord user/channel id는 Langfuse metadata에 원문으로 남기지 않고 `FINBRIEF_TRACE_SALT` 기반 hash로 기록한다.

## 8. Delivery

### `POST /api/v1/delivery/test`

Webhook 설정 검증과 시연용 테스트 발송을 수행한다.

```json
{
  "user_id": "u_001",
  "channel": "discord",
  "message": "FinBrief test"
}
```

응답:

```json
{
  "status": "sent",
  "channel": "discord",
  "delivery_id": "delivery_test_001"
}
```

## 9. Error Codes

| Code | Meaning |
| --- | --- |
| `TOPIC_LIMIT_EXCEEDED` | free tier 토픽 제한 초과 |
| `UNKNOWN_TOPIC_TYPE` | 토픽 유형 분류 실패 |
| `DATA_SOURCE_FAILED` | 외부 지표 API 실패 |
| `NEWS_INGEST_FAILED` | RSS 수집/임베딩 실패 |
| `CARD_GENERATION_FAILED` | 이미지 또는 카드 생성 실패 |
| `DELIVERY_FAILED` | Discord 발송 실패 |
| `LLM_GATEWAY_FAILED` | LiteLLM retry/fallback 이후에도 실패 |
| `INGESTION_REPOSITORY_UNAVAILABLE` | 실데이터 저장소 없이 refresh/ingest 요청 |
