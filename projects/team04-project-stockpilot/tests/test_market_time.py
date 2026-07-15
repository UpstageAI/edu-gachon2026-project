"""장 시간 기준 뉴스 시점 분류 테스트."""
from app.core.market_time import classify_session, tag_session


def test_classify_session():
    assert classify_session("2026-07-08T23:00:00+00:00") == "장 시작 전"   # 08:00 KST
    assert classify_session("2026-07-09T00:33:00+00:00") == "장 시작 후"   # 09:33 KST
    assert classify_session("2026-07-09T04:00:00+00:00") == "장 마감 전"   # 13:00 KST
    assert classify_session("2026-07-09T07:00:00+00:00") == "장 마감 후"   # 16:00 KST
    assert classify_session("2026-07-11T02:00:00+00:00") == "휴장"        # 토요일
    assert classify_session(None) == "시각 미상"


def test_tag_session():
    tagged = tag_session({"title": "실적 발표", "published_at": "2026-07-09T07:00:00+00:00"})
    assert tagged["market_session"] == "장 마감 후"
    assert tagged["title"] == "실적 발표"
