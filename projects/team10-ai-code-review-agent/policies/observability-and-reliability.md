# Observability and Reliability Policy

## 적용 범위

LiteLLM, Langfuse, Upstage API, review event, persistence, deployment, health check, retry 또는
timeout을 변경하는 PR에 적용한다.

## OBS-001 상관관계 식별자

로그와 trace는 `review_run_id`, repository, PR number, head SHA, route를 사용해 한 리뷰 실행을
연결할 수 있어야 한다. credential과 원문 secret은 metadata에 넣지 않는다.

## OBS-002 단계별 지연시간

CI 완료부터 pending check 생성, GitHub data 수집, RAG, LLM, comment 게시까지의 시간을
분리해 측정한다. 평균만 사용하지 않고 diff 구간별 p50과 p95를 기록한다.

## REL-001 실패 분류

GitHub, Upstage, Langfuse, database 오류를 구분하고 timeout, rate limit, invalid response를
실패 원인으로 남긴다. 관측성 전송 실패가 리뷰 결과 자체를 실패시키면 안 된다.

## REL-002 안전한 배포

새 image 배포 후 health check가 통과해야 완료로 판단한다. 정책 문서 변경은 배포 과정에서
policy index에 동기화되어야 하며, 실패 시 이전 실행 image와 database volume을 보존한다.
