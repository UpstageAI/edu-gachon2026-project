from app.agents import nodes


def test_verify_number_mismatch():
    good = {"category": "MARKET", "source": "s", "body": "b", "headline": "나스닥 상승", "lead": "나스닥 18120.3 (+0.78%)"}
    ok, _ = nodes._verify(good, {"value": 18120.3, "change_pct": 0.78})
    assert ok
    bad = {**good, "lead": "나스닥 99999.9 (+9.99%)"}
    ok2, iss = nodes._verify(bad, {"value": 18120.3, "change_pct": 0.78})
    assert not ok2 and "number-mismatch" in iss
