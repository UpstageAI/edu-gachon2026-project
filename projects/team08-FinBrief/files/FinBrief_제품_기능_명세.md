# FEATURE_SPEC - FinBrief

## 1. Product Summary

FinBrief는 매일 아침 주요 거시 금융 지표와 경제 뉴스를 수집해 전체 지표 리포트 이미지와 사용자 관심 토픽별 카드뉴스를 자동 생성하고, Discord 챗봇/채널로 전달하는 AI 금융 브리핑 에이전트다.

핵심 약속은 다음 한 문장이다.

> 매일 아침, 내 관심 지표를 시각화된 카드 한 장으로 자동으로 받아본다.

## 2. Problem

개인 투자자와 금융 뉴스 팔로워는 환율, 금리, 유가, 금, 비트코인, 나스닥, S&P 등 주요 지표와 관련 뉴스를 여러 서비스에서 따로 확인한다. 숫자는 쉽게 볼 수 있지만, 출근 전 5분 안에 "무엇이 움직였고 어떤 뉴스가 함께 언급되는지"를 안전하고 짧게 정리하기 어렵다.

FinBrief는 흩어진 지표와 뉴스를 한 번에 모아, 투자 조언이 아닌 참고용 브리핑으로 제공한다.

## 3. Target Users

| Persona | Need | Success Moment |
| --- | --- | --- |
| 30대 직장인 개인 투자자 | 출근 전 주요 시장 분위기를 빠르게 파악 | Discord에서 관심 토픽 카드뉴스를 1분 안에 읽음 |
| 금융·경제 뉴스 팔로워 | 지표와 관련 뉴스 맥락을 함께 확인 | 전체 지표 리포트와 토픽 카드가 같은 기준으로 정리됨 |
| 시간이 부족한 초보 투자자 | 여러 앱을 열지 않고 안전한 참고용 요약을 받음 | 과장 없는 수치 근거와 disclaimer를 확인 |

## 4. MVP Scope

### Included

- 관심 토픽 구독 설정, 조회, 삭제
- free tier 기본 5개 토픽 제한
- 거시지표 수집: 환율, 금리, 유가, 금, 비트코인, 나스닥, S&P
- 어제/오늘 값과 변화율 계산
- 경제 뉴스 RSS 수집, 임베딩, Supabase pgvector 저장
- 날짜 필터와 토픽 유사도 기반 RAG 검색
- 전체 지표 리포트 이미지 생성
- 토픽별 카드뉴스 생성: 지표 대시보드, AI 생성 이미지, 관련 뉴스, disclaimer
- 토픽+날짜 기준 카드 캐싱
- report run, report explanation, card source explanation 저장소 기반 공유
- 당일 지표 리포트 설명: 변동이 큰 지표와 RSS/RAG 뉴스 근거 설명
- 카드뉴스 출처 설명: 카드 evidence 또는 RAG 뉴스 출처와 링크 제공
- 구독자별 FanOut 발송
- Discord bot/channel 발송 MVP
- LiteLLM retry/fallback, 금융 guardrail, Langfuse report/chatbot trace, 자동 평가 세트

### Excluded

- 카카오 알림톡 실제 발송
- 실제 결제와 과금 처리
- 급변동 심층분석 루프
- 대규모 다중 사용자 운영
- 매매 추천, 투자 판단, 자동 주문
- Discord button/select UI와 장기 대화 메모리

## 5. Core User Flow

1. 사용자가 Discord 챗봇에서 관심 토픽을 자연어로 등록한다.
2. 시스템이 토픽 유형을 `indicator`, `keyword`, `sector`, `asset` 중 하나로 분류하고 모호하면 후보를 제시한다.
3. 매일 08:00 스케줄러 또는 `/reports/run` API가 뉴스와 지표를 수집한다.
4. 전체 지표 리포트 이미지를 생성하고 report result repository에 저장한다.
5. 전체 구독 목록에서 오늘 필요한 토픽을 중복 제거한다.
6. 토픽별로 RAG 검색, 분석, 이미지 생성, 카드 조합을 병렬 수행한다.
7. 생성된 카드는 토픽+날짜로 캐시한다.
8. 각 구독자에게 해당 카드 링크 또는 이미지와 요약을 Discord로 발송한다.
9. 사용자는 필요할 때 관리 챗봇에서 토픽을 추가/삭제하고, 당일 리포트 설명 또는 카드뉴스 출처 설명을 요청한다.

## 6. Agent Responsibilities

| Agent Capability | Description | Guardrail |
| --- | --- | --- |
| 관리 챗봇 | 구독·토픽 CRUD, 티어 조회, 추천, 리포트 설명, 카드 출처 설명, 기능 외 자연어 안내 | 투자 판단 차단, 모호한 토픽 후보 제시, LLM 안내는 실제 구현 기능 범위로 제한 |
| 지표 수집 | FRED, yfinance, ECOS에서 값 수집 | 실패한 지표는 제외하고 fallback 발송 |
| 뉴스 수집/RAG | RSS 수집, 임베딩, 토픽 관련 뉴스 검색 | 날짜 필터와 출처 메타데이터 포함 |
| 분석·요약 | 수치 변화와 뉴스 맥락을 짧게 설명 | 단정·과장 금지, 투자 조언 금지 |
| 카드 생성 | 대시보드 이미지, AI 이미지, 관련 뉴스 조합 | 토픽+날짜 캐시 재사용 |
| 결과 공유 | scheduler/API/bot 간 report result, report explanation, card source explanation 공유 | Supabase/memory repository 계약으로 프로세스 분리 배포에서도 조회 가능 |
| 발송 | Discord bot/webhook 전송 | 채널 실패 기록, 재시도, partial success 허용 |

## 7. Topic Model

| Type | Examples | Data Source |
| --- | --- | --- |
| `indicator` | USD/KRW 환율, 미국 금리, 나스닥, S&P | FRED, yfinance, ECOS + 뉴스 |
| `keyword` | AI, 반도체, 전기차 | 뉴스 RSS + RAG |
| `sector` | IT, 바이오 | 대표 ETF/지수 + 섹터 뉴스 |
| `asset` | 금, 비트코인, 원유 | 가격 API + 관련 뉴스 |

free tier 기본 토픽은 `USD/KRW 환율`, `미국 금리`, `나스닥`, `비트코인`, `반도체`로 둔다.

## 8. Acceptance Criteria

- AC1: 사용자는 관심 토픽을 추가, 조회, 삭제할 수 있다.
- AC2: free tier 사용자는 최대 5개 토픽까지만 저장할 수 있다.
- AC3: 매일 배치 실행 1회가 전체 지표 리포트와 토픽 카드 최소 1개를 생성한다.
- AC4: 같은 날짜의 같은 토픽 카드는 한 번만 생성되고 여러 구독자에게 재사용된다.
- AC5: 지표 일부 수집 실패 시 실패 항목을 표시하고 나머지 항목으로 발송한다.
- AC6: 모든 리포트와 카드에는 "투자 조언이 아닌 참고용" disclaimer가 포함된다.
- AC7: Discord 발송 결과는 성공, 실패, 재시도 여부와 함께 기록된다.
- AC8: LiteLLM, Langfuse, 자동 평가 로그로 모델 호출·비용·품질 근거를 남긴다.
- AC9: 사용자는 챗봇으로 당일 리포트 설명과 카드뉴스 출처 설명을 요청할 수 있다.
- AC10: API, scheduler, Discord bot은 같은 저장소에 저장된 report/card 결과를 공유한다.
- AC11: 기능 외 자연어 입력은 LLM이 실제 구현 기능 범위 안에서 적절한 안내문으로 응답한다.
