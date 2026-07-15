# Testing and Routing Policy

## 적용 범위

라우팅 규칙, check result parsing, LangGraph node, RAG retrieval, prompt builder, publisher를
변경하는 모든 PR에 적용한다.

## TEST-001 라우팅 회귀 테스트

문법, lint 또는 test 실패는 `simple_failure_review`와 low reasoning으로 가야 한다. check가
실패하지 않은 자동 리뷰는 `policy_context_review`와 medium reasoning을 사용해야 한다.
심층 리뷰 action은 `deep_quality_review`와 high reasoning을 사용해야 한다.

## TEST-002 이벤트 순서 테스트

`after_checks` 모드에서 PR event는 대기 상태여야 하고, 완료된 check suite만 리뷰 요청을
생성해야 한다. draft PR, self check event, 지원하지 않는 action은 리뷰를 만들지 않아야 한다.

## TEST-003 정책 근거 테스트

RAG 변경에는 관련 query가 기대 정책을 top-k에서 찾는 positive fixture와 무관한 정책을
반환하지 않는 negative fixture를 모두 추가한다. finding의 policy source는 실제 검색된
source path와 section title이어야 한다.

## TEST-004 외부 API 격리

CI unit test는 Upstage와 GitHub의 실제 API를 호출하지 않는다. fake client 또는 mock mode로
성공, timeout, rate limit, 잘못된 JSON 응답을 재현할 수 있어야 한다.
