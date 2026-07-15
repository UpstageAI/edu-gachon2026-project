# AI Review Policy

## API Contract

- 공개 API와 webhook payload의 기존 필드, status code, 인증 경계를 변경하면 호환성과 migration 방법을 함께 검토한다.
- GitHub API 요청은 installation token 범위 안에서 수행하고 token이나 private key를 log에 기록하지 않는다.

## Test Policy

- 외부 GitHub나 LLM 호출을 검증하는 단위 테스트는 fake 또는 mock을 사용해 network와 credential에 의존하지 않는다.
- 회귀 테스트는 구현 세부 호출 횟수보다 사용자에게 보이는 동작과 실패 조건을 검증한다.

## Performance and Python Complexity

- Python 심층 리뷰의 cyclomatic complexity는 Radon 측정값만 근거로 사용한다.
- 변경 후 함수 값이 15를 초과하고 변경 전보다 증가한 경우에만 복잡도 finding을 허용한다.
- 모델은 측정값을 추측하지 않고 중첩 분기를 줄이는 동작 보존 리팩터링만 제안한다.
