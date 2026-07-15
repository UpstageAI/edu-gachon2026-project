"""테스트 격리 공통 설정.

app.main이 import 시 load_dotenv()로 실제 Supabase/LLM 자격증명을 os.environ에 올리기
때문에, 목킹이 빠진 코드 경로가 운영 서비스에 도달할 수 있다(실제로 inquiry_logs에
잘못된 테스트용 inquiry_id "inq-1"로 INSERT가 나가 운영 DB에 ERROR가 쌓인 사례가 있었다).

아래 autouse 픽스처로 모든 테스트 시작 전에 외부 서비스 환경변수를 제거한다.
- 목킹된 테스트: 영향 없음.
- 목킹이 빠진 호출: 운영에 도달하는 대신 env() RuntimeError로 로컬에서 안전하게 실패.
- 특정 값이 필요한 테스트: 각자 monkeypatch.setenv로 설정한다(픽스처보다 나중에 실행됨).
"""

import pytest

_EXTERNAL_ENV_VARS = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_DOCUMENTS_TABLE",
    "SUPABASE_INQUIRIES_TABLE",
    "SUPABASE_INQUIRY_LOGS_TABLE",
    "UPSTAGE_BASE_URL",
    "UPSTAGE_API_KEY",
    "UPSTAGE_EMBEDDING_QUERY_MODEL",
    "UPSTAGE_EMBEDDING_PASSAGE_MODEL",
    "LITELLM_BASE_URL",
    "LITELLM_MASTER_KEY",
    "LITELLM_CHAT_MODEL",
)


@pytest.fixture(autouse=True)
def block_real_external_services(monkeypatch):
    """실제 외부 서비스로의 우발적 네트워크 호출을 차단한다."""
    for name in _EXTERNAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
