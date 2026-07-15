# API Contract Policy

## 적용 범위

FastAPI handler, request/response schema, `/v1/` endpoint, HTTP status code, webhook response를
변경하는 PR에 적용한다. 관련 경로는 `backend/app/main.py`, `backend/app/core/schemas.py`다.

## API-001 안정적인 응답 계약

공개 API 응답 필드의 이름과 타입을 변경할 때는 기존 호출자에 대한 호환성 또는 migration
방법을 명시해야 한다. API response, response field, backward compatibility를 검토하고 성공
응답과 오류 응답은 endpoint별로 예측 가능한 구조를 유지한다.

## API-002 오류 처리

클라이언트 입력 오류는 4xx, 외부 의존성이나 서버 오류는 5xx로 구분한다. 내부 exception,
database 필드, access token, private key를 응답에 노출하지 않는다.

## API-003 Webhook 응답

GitHub webhook은 서명과 필수 header를 검증한 뒤 빠르게 2xx를 반환하고 긴 리뷰 작업은
background workflow로 넘긴다. 동일 delivery와 PR head SHA는 중복 리뷰를 만들지 않아야 한다.

## API-004 계약 테스트

endpoint 응답 필드나 status code를 바꾸는 PR에는 정상, 인증 실패, 잘못된 payload 중 변경과
관련된 API-level test를 추가한다.
