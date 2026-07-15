# Security and Privacy Policy

## 적용 범위

authentication, authorization, webhook secret, API key, private key, token, prompt logging,
database 또는 Docker network를 변경하는 PR에 적용한다.

## SEC-001 입력 검증 순서

GitHub webhook body는 JSON parsing보다 먼저 `X-Hub-Signature-256`을 검증한다. 인증에 실패한
payload는 background task, database, LLM으로 전달하지 않는다.

## SEC-002 Secret 마스킹

diff와 check log는 LLM 또는 Langfuse로 보내기 전에 secret masking을 적용한다. Upstage API
key, GitHub installation token, private key, database password는 prompt, comment, trace metadata에
포함하지 않는다.

## SEC-003 데이터 최소화

리뷰에 필요한 patch와 check summary만 제한된 길이로 전달한다. 원본 repository 전체,
불필요한 개인정보, 전체 CI log를 장기 저장하지 않는다.

## SEC-004 네트워크 노출

외부에는 Caddy의 80/443만 공개한다. Postgres 5432와 application 8080은 loopback 또는 내부
Docker network에만 bind하고 운영 DB 접근은 IAP SSH tunnel을 사용한다.
