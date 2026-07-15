from app.agents import nodes


def test_fmt_value_pt_is_integer():
    # 지수(pt)는 정수로 반올림
    assert nodes._fmt_value(26281.609375, "pt") == "26282"
    assert nodes._fmt_value(3200.0, "pt") == "3200"


def test_fmt_value_currency_two_decimals_trimmed():
    # 달러/USD 등은 소수 2자리(불필요한 0 제거), 원은 정수(한국 종목/환율)
    assert nodes._fmt_value(62780.3200001, "USD") == "62780.32"
    assert nodes._fmt_value(203.53, "달러") == "203.53"
    assert nodes._fmt_value(256500.0, "원") == "256500"
    assert nodes._fmt_value(1234.0, "달러") == "1234"


def test_fmt_pct_two_decimals():
    assert nodes._fmt_pct(0.28511108421508896) == "0.29"
    assert nodes._fmt_pct(-1.2000) == "-1.2"
    assert nodes._fmt_pct(0) == "0"


def test_fmt_handles_none_and_bad():
    assert nodes._fmt_value(None, "pt") == ""
    assert nodes._fmt_pct(None) == "0"
    assert nodes._fmt_value("N/A", "pt") == "N/A"


def test_user_prompt_contains_rounded_numbers():
    topic = {"name": "나스닥", "category": "MARKET", "topic_id": "topic_nasdaq"}
    data = {"value": 26281.609375, "change_pct": 0.28511108421508896, "unit": "pt"}
    prompt = nodes._user_prompt(topic, data, [{"title": "t", "snippet": "s"}])
    assert "26282" in prompt
    assert "0.29" in prompt
    # 원시 미반올림 숫자는 프롬프트에 없어야 함
    assert "26281.609375" not in prompt
    assert "0.28511108421508896" not in prompt
