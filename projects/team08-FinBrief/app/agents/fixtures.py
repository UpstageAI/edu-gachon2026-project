"""Phase 0 fixtures — 팀원 데이터 파트 실구현 전, 그래프 관통용 더미 데이터.
   실제로는 tools/repositories 가 채운다. Phase 4에서 제거."""

FIXTURE_TOPICS = [
    {"topic_id": "usdkrw", "name": "원/달러 환율", "category": "FX"},
    {"topic_id": "us_rate", "name": "미국 기준금리", "category": "GLOBAL"},
    {"topic_id": "nasdaq", "name": "나스닥", "category": "MARKET"},
    {"topic_id": "btc", "name": "비트코인", "category": "CRYPTO"},
    {"topic_id": "semi", "name": "반도체", "category": "MARKET"},
]
FIXTURE_SUBSCRIPTIONS = [
    {"user_id": "u1", "channel": "discord", "topic_id": "nasdaq", "discord_channel_id": "111"},
    {"user_id": "u1", "channel": "discord", "topic_id": "btc", "discord_channel_id": "111"},
    {"user_id": "u2", "channel": "discord", "topic_id": "nasdaq", "discord_channel_id": "222"},
    {"user_id": "u2", "channel": "discord", "topic_id": "semi", "discord_channel_id": "222"},
]
FIXTURE_INDICATORS = {
    "usdkrw": {"value": 1378.5, "prev": 1372.0, "change_pct": 0.47, "unit": "KRW"},
    "us_rate": {"value": 4.50, "prev": 4.50, "change_pct": 0.0, "unit": "%"},
    "nasdaq": {"value": 18120.3, "prev": 17980.1, "change_pct": 0.78, "unit": "pt"},
    "btc": {"value": 68450.0, "prev": 66900.0, "change_pct": 2.32, "unit": "USD"},
    "semi": {"value": 5210.4, "prev": 5155.0, "change_pct": 1.07, "unit": "pt"},
}
FIXTURE_NEWS = {
    "nasdaq": [{"news_id": "n1", "title": "기술주 강세에 나스닥 상승", "source": "예시통신",
                "url": "https://example.com/n1", "similarity": 0.82, "snippet": "AI 반도체 수요..."}],
    "btc": [{"news_id": "n2", "title": "위험자산 선호 회복, 비트코인 반등", "source": "예시통신",
             "url": "https://example.com/n2", "similarity": 0.79, "snippet": "금리 인하 기대..."}],
    "semi": [{"news_id": "n3", "title": "HBM 수요로 반도체주 강세", "source": "예시통신",
              "url": "https://example.com/n3", "similarity": 0.85, "snippet": "데이터센터 투자..."}],
    "usdkrw": [], "us_rate": [],
}
