# StockPilot

## 1. 프로젝트 소개

StockPilot은 주식을 잘 모르는 사용자도 종목의 현재 흐름을 쉽게 이해할 수 있도록 돕는 **투자 기반 리서치 Agent**입니다.

사용자가 “삼성전자 요즘 어때?”, “왜 올랐어?”, “공시 리스크 알려줘”, “급등 종목 추천”처럼 자연어로 질문하면 Solar ReAct Agent가 필요한 도구를 선택하고, 시세·뉴스·공시·투자용어 정보를 모아 근거와 출처 기반으로 설명합니다.

- 한 줄 소개: 종목 질문 하나로 시세·뉴스·공시·용어를 함께 분석해 주가 흐름의 이유를 설명하는 AI 주식 리서치 서비스
- 주요 사용자: 주식 초보자, 공시·뉴스 해석이 어려운 개인 투자자, 빠르게 근거를 확인하고 싶은 리서치 사용자
- 최종 결과물: React 웹 UI, FastAPI 백엔드, LangGraph ReAct Agent, Supabase RAG, GCE 배포 서비스

---

## 2. 문제 정의

개인 투자자는 종목을 볼 때 증권 앱의 시세, 포털 뉴스, DART 공시, 재무 정보, 투자용어를 각각 따로 확인해야 합니다.

기존 방식의 한계는 다음과 같습니다.

- 정보 파편화: 시세, 뉴스, 공시가 서로 다른 서비스에 흩어져 있어 종합 판단에 시간이 걸림
- 근거 부족: “왜 올랐는지/떨어졌는지”에 대한 설명이 없거나 출처가 불명확함
- 해석 난이도: 초보자는 공시 제목, 재무 용어, 시장 표현을 이해하기 어려움
- 투자 자문 리스크: 단순 추천·예측형 답변은 사용자가 오해할 가능성이 큼

---

## 3. 문제 해결

StockPilot은 사용자의 질문을 입력 가드레일로 먼저 검증한 뒤, Solar ReAct Agent가 `Thought → Action → Observation` 루프로 필요한 도구와 RAG 검색을 선택해 답변을 생성합니다.

현재 제출 버전의 기본 실행 경로는 `agent_mode=full_react`이며, 기존 규칙 기반 라우터는 비교·회귀 테스트용 경로로만 남겨두었습니다.

전체 흐름은 다음과 같습니다.

1. 사용자가 자연어로 종목 또는 투자 관련 질문 입력
2. 입력 가드레일이 범위 밖 질문, 매수·매도 추천, 목표가 예측, 민감정보 입력을 사전 차단
3. Solar ReAct Agent가 다음 행동을 판단하고 필요한 경우 ToolExecutor의 Pydantic Tool Schema를 통해 도구 호출
4. pykrx, 네이버 뉴스 API, OpenDART, Supabase pgvector RAG 결과를 Observation으로 받아 다시 판단
5. 충분한 근거가 모이면 초보자도 이해하기 쉬운 답변 초안을 생성
6. 출력 가드레일이 투자 권유·예측 표현을 후처리한 뒤 SSE로 실시간 출력

이를 통해 사용자는 한 번의 질문으로 주가 흐름, 관련 뉴스, 공시, 용어 설명을 함께 확인할 수 있습니다.

---

## 4. 핵심 기능

- 종목 흐름 요약: 현재가, 전일 대비 등락률, 일봉 차트, 최근 흐름을 초보자 친화적으로 설명
- 상승·하락 원인 분석: 사용자가 “왜 올랐어/왜 떨어졌어”라고 물으면 뉴스와 공시 근거 기반으로 설명
- 뉴스 수집: 네이버 검색 API를 통해 종목 관련 최신 뉴스 조회 및 근거 카드 제공
- 공시 조회: OpenDART API를 통해 최근 공시 목록과 주요 리스크 확인
- 투자용어 RAG: Supabase pgvector에 적재한 용어·문서 기반으로 어려운 투자용어 설명
- 스크리너: 최근 상승률과 긍정 뉴스 기반으로 참고용 종목 후보 조회
- 세션 기반 대화: 로그인 사용자의 최근 대화와 문맥을 유지
- 안전장치: 매수·매도 추천, 구체적 가격 예측, 신용카드 등 민감정보 입력을 차단
- ReAct 도구 실행: Solar가 시세·뉴스·공시·용어·스크리너 도구를 직접 선택하고 결과를 관찰하며 답변 생성
- 배포/운영: Docker Compose, GCE VM, GitHub Actions CI/CD, Langfuse 관측 적용

---

## 5. 데모 영상

- 데모 영상: 준비 중
- 배포 URL: http://34.172.154.165
- 원본 프로젝트 저장소: https://github.com/jjh0813/StockPilot
- 추가 시연 자료: 발표자료 및 실행 화면 캡처

---

## 6. 팀원 소개

| 이름 | 역할 | GitHub |
|---|---|---|
| jaesang02 | Data, Backend, RAG, Infra | @jaesang02 |
| jjh0813 | Frontend, Backend, Agent | @jjh0813 |

---

## 7. 참고자료 / 발표자료

- 발표자료: 최종 발표 PPT
- 기획서: StockPilot 프로젝트 기획서
- 참고한 문서: Upstage Solar API, OpenDART API, Naver Search API, pykrx, Supabase pgvector, LangGraph, FastAPI
- 참고한 오픈소스: React, Vite, lightweight-charts, FastAPI, LangGraph, Supabase Python Client
- 기타 자료: Langfuse trace, GitHub Actions CI/CD 결과, 회귀 테스트 결과
