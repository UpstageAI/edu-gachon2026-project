"""agent/mock_llm.py 단위 테스트 (키워드 매칭 규칙 검증)."""
from __future__ import annotations

from app.agent.mock_llm import MockLLM
from app.schemas.tools import Importance


def test_two_or_more_keyword_hits_yield_very_high():
    intent = MockLLM().parse_intent("안전하고 무서운 밤길이 걱정돼요")
    assert intent.preference.safety == Importance.VERY_HIGH
    assert intent.preference.convenience == Importance.NONE
    assert intent.preference.mobility == Importance.NONE
    assert intent.preference.environment == Importance.NONE
    assert intent.needs_clarification is False


def test_single_keyword_hit_yields_high():
    intent = MockLLM().parse_intent("병원 근처가 좋아요")
    assert intent.preference.convenience == Importance.HIGH
    assert intent.preference.safety == Importance.NONE
    assert intent.preference.mobility == Importance.NONE
    assert intent.preference.environment == Importance.NONE


def test_no_keyword_hits_triggers_clarification():
    intent = MockLLM().parse_intent("오늘 날씨가 좋네요")
    assert intent.needs_clarification is True
    assert intent.clarify_question
    assert all(v == Importance.NONE for v in intent.preference.model_dump().values())


def test_multiple_categories_can_be_detected_simultaneously():
    intent = MockLLM().parse_intent("안전하고 무서운 밤길 말고, 공원 산책하기 좋은 조용한 동네")
    assert intent.preference.safety == Importance.VERY_HIGH
    assert intent.preference.environment == Importance.VERY_HIGH
    assert intent.needs_clarification is False


# ---------- extra_categories (임의 업종) ----------

def test_facility_synonym_maps_free_text_to_real_category_label():
    intent = MockLLM().parse_intent("버거집 있는 동네가 좋아요")
    assert intent.extra_categories == ["버거"]
    assert intent.needs_clarification is False


def test_facility_synonym_expands_one_word_to_multiple_categories():
    intent = MockLLM().parse_intent("운동할 수 있는 곳이 있었으면")
    assert set(intent.extra_categories) == {"헬스장", "수영장", "종합 스포츠시설"}


def test_facility_only_request_does_not_trigger_clarification():
    """4개 카테고리 언급이 전혀 없어도 업종이 언급됐으면 되묻지 않아야 한다."""
    intent = MockLLM().parse_intent("헬스장 있는 곳")
    assert intent.needs_clarification is False


def test_no_facility_keyword_leaves_extra_categories_empty():
    intent = MockLLM().parse_intent("안전한 동네가 좋아요")
    assert intent.extra_categories == []


# ---------- explain ----------

def test_explain_no_recommendations_returns_fixed_message():
    msg = MockLLM().explain("아무 텍스트", {"recommendations": []})
    assert msg == "조건에 맞는 지역을 찾지 못했습니다."


def _fake_result(hosp_cnt: int, weights: dict | None = None,
                  contributions: dict | None = None) -> dict:
    raw = dict(crime_rate=1.0, cctv_cnt=2, conv_cnt=3, mart_cnt=4,
               hosp_cnt=hosp_cnt, bus_cnt=5, subway_access=0.7, park_cnt=6)
    rec = {"gu": "강남구", "dong": "역삼동", "total_score": 0.5, "scores": {"raw": raw}}
    if contributions is not None:
        rec["contributions"] = contributions
    result = {"recommendations": [rec]}
    if weights is not None:
        result["weights"] = weights
    return result


def test_explain_names_the_dong_but_hides_raw_metric_values():
    """Step 2/3 UX 개선: 내부 계산은 그대로 두되, 사용자 문장에는 raw 수치가
    노출되면 안 된다 (hover/필터 검증 expander에 이미 별도로 노출되므로 중복 불필요)."""
    msg = MockLLM().explain("조용한 동네", _fake_result(hosp_cnt=1))
    assert "강남구 역삼동" in msg
    assert "CCTV" not in msg
    assert "편의점 3" not in msg
    assert "마트 4" not in msg
    assert "버스 5개" not in msg
    assert "공원 6곳" not in msg


def test_explain_flags_missing_large_hospital():
    msg = MockLLM().explain("대형병원 근처였으면", _fake_result(hosp_cnt=0))
    assert "다만 요청하신 대형병원은 근처에서 확인되지 않았습니다." in msg


def test_explain_no_warning_when_hospital_present():
    msg = MockLLM().explain("대형병원 근처였으면", _fake_result(hosp_cnt=1))
    assert "다만 요청하신 대형병원은 근처에서 확인되지 않았습니다." not in msg


def test_explain_uses_natural_reasons_from_contributions_not_raw_numbers():
    result = _fake_result(
        hosp_cnt=1,
        weights={"safety": 0.5, "mobility": 0.5, "convenience": 0.0, "environment": 0.0},
        contributions={"safety": 0.4, "mobility": 0.3, "convenience": 0.0, "environment": 0.0},
    )
    msg = MockLLM().explain("안전하고 이동 편한 곳", result)
    assert "체감 안전도" in msg  # safety 자연어 이유
    assert "대중교통" in msg  # mobility 자연어 이유
    assert "0.4" not in msg and "0.3" not in msg  # 실제 기여도 수치는 노출 안 됨
    assert "편의점" not in msg  # 기여도 0인 항목은 이유로 언급 안 됨


def test_explain_falls_back_gracefully_without_weights_or_contributions():
    """weights/contributions가 없어도(구버전 호출) 죽지 않고 균형 문구로 대체돼야 한다."""
    msg = MockLLM().explain("아무 텍스트", _fake_result(hosp_cnt=1))
    assert "여러 조건을 고르게 충족하는 동네입니다" in msg


def test_explain_appends_caveat_for_prioritized_category():
    result = _fake_result(hosp_cnt=1, weights={
        "safety": 1.0, "convenience": 0.0, "mobility": 0.0, "environment": 0.0})
    msg = MockLLM().explain("안전한 곳", result)
    assert "자치구 값을 공통 적용" in msg  # safety 각주 (구 상속) — 숫자 없이 방법론만 설명


def test_explain_omits_caveats_for_categories_the_user_did_not_prioritize():
    result = _fake_result(hosp_cnt=1, weights={
        "safety": 1.0, "convenience": 0.0, "mobility": 0.0, "environment": 0.0})
    msg = MockLLM().explain("안전한 곳", result)
    assert "최근접 역까지 거리" not in msg  # mobility 각주는 언급 안 됨


def test_explain_has_no_caveat_when_no_weights_given():
    msg = MockLLM().explain("아무 텍스트", _fake_result(hosp_cnt=1))
    assert "참고:" not in msg


def test_explain_reports_extra_facility_count_when_present():
    result = _fake_result(hosp_cnt=1)
    result["recommendations"][0]["extra_facilities"] = {"버거": 3}
    msg = MockLLM().explain("버거집 있는 곳", result)
    assert "버거" in msg and "3곳" in msg


def test_explain_flags_extra_facility_not_found():
    result = _fake_result(hosp_cnt=1)
    result["recommendations"][0]["extra_facilities"] = {"헬스장": 0}
    msg = MockLLM().explain("헬스장 있는 곳", result)
    assert "다만 요청하신 '헬스장'은 이 동네에서는 확인되지 않았습니다." in msg


def test_explain_notes_extra_facility_counting_methodology():
    result = _fake_result(hosp_cnt=1)
    result["recommendations"][0]["extra_facilities"] = {"버거": 2}
    msg = MockLLM().explain("버거집 있는 곳", result)
    assert "해당 행정동에 등록된 업소 수 기준" in msg


def test_explain_no_extra_facility_note_when_not_requested():
    msg = MockLLM().explain("안전한 곳", _fake_result(hosp_cnt=1))
    assert "등록된 업소 수 기준" not in msg


def test_explain_reports_unsupported_noise_and_soundproofing_limits():
    msg = MockLLM().explain(
        "집에서 집중해야 해서 조용하고 방음이 잘 되는 곳, 공원도 가까운 곳",
        _fake_result(hosp_cnt=1),
    )
    assert "조용함/소음/방음" in msg
    assert "소음도" in msg


def test_explain_reports_rent_limit_only_when_price_is_requirement():
    background_only = MockLLM().explain(
        "현재 주거는 전·월세예요. 공원이 가까운 곳",
        _fake_result(hosp_cnt=1),
    )
    price_need = MockLLM().explain(
        "월세 부담이 커서 저렴한 곳이 필요해요",
        _fake_result(hosp_cnt=1),
    )

    assert "월세/전세/주거비" not in background_only
    assert "월세/전세/주거비" in price_need


# ---------- explain_stream (SSE 테스트용) ----------

def test_explain_stream_reconstructs_same_text_as_explain():
    result = _fake_result(hosp_cnt=1)
    full = MockLLM().explain("조용한 동네", result)
    streamed = "".join(MockLLM().explain_stream("조용한 동네", result))
    assert streamed == full


def test_explain_stream_yields_multiple_chunks_for_long_message():
    result = _fake_result(hosp_cnt=1)
    chunks = list(MockLLM().explain_stream("조용한 동네", result))
    assert len(chunks) > 1
