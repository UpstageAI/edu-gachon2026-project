import os

# app.main이 임포트되는 순간 init_langfuse()가 실행되어 .env의 실제 키로 Langfuse
# 클라이언트가 초기화된다(app/main.py, app/core/observability.py). public_key를
# 지우는 방식은 langfuse SDK가 `os.environ.get(...)`을 `is None`으로만 체크해서
# 빈 문자열은 "설정됨"으로 취급돼 오히려 잘못된 URL로 전송을 시도하게 만든다.
# 대신 SDK가 공식 지원하는 킬스위치인 LANGFUSE_TRACING_ENABLED=false를 그 어떤
# 앱 모듈이 임포트되기 전에(conftest.py는 pytest가 테스트 모듈보다 먼저 임포트한다)
# 설정해, 실제 키가 전달되더라도 트레이서 자체가 생성되지 않도록 한다.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
