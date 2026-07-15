import pytest

from app.core.config import Settings
from app.repositories.supabase_client import SupabaseSettingsError, create_supabase_client
from app.repositories.supabase import map_news_match_result


def test_create_supabase_client_requires_url_and_service_role_key():
    settings = Settings(
        supabase_url="",
        supabase_service_role_key=None,
    )

    with pytest.raises(SupabaseSettingsError) as exc_info:
        create_supabase_client(settings)

    assert "SUPABASE_URL" in str(exc_info.value)


def test_supabase_repository_import_does_not_require_supabase_environment():
    import app.repositories.supabase as supabase_repository

    assert hasattr(supabase_repository, "SupabaseRepositories")


def test_map_news_match_result_to_news_evidence_uses_summary_as_snippet():
    evidence = map_news_match_result(
        {
            "news_id": "n_001",
            "title": "나스닥 상승",
            "source": "fixture",
            "url": "https://example.com/news",
            "summary": "기술주 중심으로 상승했습니다.",
            "similarity": 0.92,
        }
    )

    assert evidence.news_id == "n_001"
    assert evidence.snippet == "기술주 중심으로 상승했습니다."
    assert evidence.similarity == 0.92
