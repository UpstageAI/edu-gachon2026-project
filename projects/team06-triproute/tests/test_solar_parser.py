from app.core.config import settings
from app.services.solar import parse_trip_request
from app.services.upstage_client import (
    _build_solar_messages,
    _detect_city,
    _detect_prefer_local,
)


def test_solar_parser_fallback_without_api_key(monkeypatch):
    # 테스트 실행 중에만 설정 객체의 API 키를 제거
    monkeypatch.setattr(
        settings,
        "UPSTAGE_API_KEY",
        "",
        raising=False,
    )

    result, warnings = parse_trip_request(
        "강릉으로 1박 2일 여행 가고 싶어. "
        "바다랑 감성 카페를 좋아해."
    )

    assert result["city"] == "강릉"
    assert result["duration"] == "1박 2일"
    assert result["_parser"] == "mock"
    assert result["prefer_local"] is False
    assert warnings


def test_solar_parser_fallback_detects_prefer_local(monkeypatch):
    monkeypatch.setattr(
        settings,
        "UPSTAGE_API_KEY",
        "",
        raising=False,
    )

    result, _ = parse_trip_request(
        "사람 안 몰리는 로컬 맛집 위주로 다니고 싶어."
    )

    assert result["prefer_local"] is True


def test_detect_prefer_local_keywords():
    assert _detect_prefer_local("현지인만 아는 숨은 명소로 가고 싶어") is True
    assert _detect_prefer_local("유명한 관광지 위주로 다니고 싶어") is False


def test_solar_parser_fallback_detects_other_city(monkeypatch):
    monkeypatch.setattr(
        settings,
        "UPSTAGE_API_KEY",
        "",
        raising=False,
    )

    result, _ = parse_trip_request("부산으로 2박 3일 여행 갈 거야.")

    assert result["city"] == "부산"


def test_detect_city_keywords():
    assert _detect_city("부산으로 여행 가고 싶어") == "부산"
    assert _detect_city("몽골로 여행 가고 싶어") is None


def test_build_solar_messages_without_previous_context_is_unchanged():
    messages = _build_solar_messages("강릉으로 1박 2일 여행 가고 싶어.", None)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1] == {
        "role": "user",
        "content": "강릉으로 1박 2일 여행 가고 싶어.",
    }


def test_build_solar_messages_includes_previous_context_as_multi_turn():
    previous_condition_summary = {
        "user_input": "강릉으로 1박 2일 여행 가고 싶어. 바다랑 감성 카페를 좋아해.",
        "city": "강릉",
        "season": "여름",
        "duration": "1박 2일",
        "travel_style": ["바다", "감성 카페"],
        "schedule_intensity": "여유로운 일정",
        "prefer_local": False,
        "prefer_budget": False,
        "is_peak_season": False,
        # condition_summary에만 있고 파싱 스키마엔 없는 필드들 — 걸러져야 함
        "transport_mode": "대중교통",
        "people_count": 2,
        "parser": "solar",
        "data_source": "rag",
    }

    messages = _build_solar_messages(
        "카페 말고 맛집 위주로 바꿔줘.",
        previous_condition_summary,
    )

    assert len(messages) == 4
    assert messages[1] == {
        "role": "user",
        "content": previous_condition_summary["user_input"],
    }
    assert messages[2]["role"] == "assistant"

    import json

    previous_parsed = json.loads(messages[2]["content"])
    assert previous_parsed == {
        "city": "강릉",
        "season": "여름",
        "duration": "1박 2일",
        "travel_style": ["바다", "감성 카페"],
        "schedule_intensity": "여유로운 일정",
        "prefer_local": False,
        "prefer_budget": False,
        "is_peak_season": False,
    }
    assert "transport_mode" not in previous_parsed
    assert "parser" not in previous_parsed

    assert messages[3] == {"role": "user", "content": "카페 말고 맛집 위주로 바꿔줘."}


def test_build_solar_messages_ignores_previous_context_missing_user_input():
    # user_input이 없는 previous_condition_summary는 무시하고 새 메시지만 보내야 한다
    messages = _build_solar_messages("강릉으로 여행 가고 싶어.", {"city": "강릉"})

    assert len(messages) == 2


def test_solar_parser_fallback_with_previous_context_adds_extra_warning(monkeypatch):
    monkeypatch.setattr(settings, "UPSTAGE_API_KEY", "", raising=False)

    result, warnings = parse_trip_request(
        "카페 말고 맛집 위주로 바꿔줘.",
        previous_condition_summary={
            "user_input": "강릉으로 1박 2일 여행 가고 싶어.",
            "city": "강릉",
        },
    )

    assert result["_parser"] == "mock"
    assert any("이전 대화 맥락을 반영하지 못했습니다" in warning for warning in warnings)


def test_parse_trip_request_default_previous_context_is_none(monkeypatch):
    # previous_condition_summary 없이 호출하는 기존 방식이 그대로 동작해야 한다
    monkeypatch.setattr(settings, "UPSTAGE_API_KEY", "", raising=False)

    result, warnings = parse_trip_request("강릉으로 1박 2일 여행 가고 싶어.")

    assert result["city"] == "강릉"
    assert not any("이전 대화 맥락" in warning for warning in warnings)