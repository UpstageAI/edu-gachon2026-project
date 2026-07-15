from app.agents import nodes


NVDA_TOPIC = {"name": "엔비디아", "source_key": "nvidia", "category": "MARKET", "topic_id": "topic_nvidia"}
NVDA_DATA = {"value": 203.53, "change_pct": -3.52, "unit": "달러"}


def test_topic_in_evidence_true_when_name_present():
    news = [{"title": "엔비디아 신제품 공개", "snippet": "GPU 성능 향상"}]
    assert nodes._topic_in_evidence(NVDA_TOPIC, news) is True


def test_topic_in_evidence_false_when_only_loose_keyword():
    # 근거가 냉각/애플 뉴스라 토픽명(엔비디아/nvidia)이 전혀 없음 → 무관 판정
    news = [{"title": "나인앤컴퍼니, 데이터센터 냉각", "snippet": "고성능 GPU 서버 발열 대응"},
            {"title": "애플 사상 최고가", "snippet": "반도체주 약세 속 애플 재평가"}]
    assert nodes._topic_in_evidence(NVDA_TOPIC, news) is False


def test_grounded_fallback_uses_indicator_when_value_present():
    news = [{"title": "나인앤컴퍼니 냉각 솔루션", "snippet": "GPU 발열"}]
    head, lead = nodes._grounded_fallback(NVDA_TOPIC, NVDA_DATA, news)
    assert "엔비디아" in head and "203.53달러" in head
    assert "주도권" not in head          # 근거 없는 단정이 사라짐
    assert "203.53달러" in lead and "3.52%" in lead


def test_grounded_fallback_uses_top_news_when_no_value():
    news = [{"title": "로봇 결혼식 개최", "snippet": "모스크바"}]
    topic = {"name": "로봇", "source_key": "robot", "category": "MARKET", "topic_id": "topic_robot"}
    head, _ = nodes._grounded_fallback(topic, {"value": None}, news)
    assert "로봇 결혼식" in head


def test_analyze_applies_guard_when_topic_absent(monkeypatch):
    # LLM 이 토픽 무관 근거로 '엔비디아 주도권 강화' 같은 단정을 냈을 때 가드가 사실로 대체
    monkeypatch.setattr(nodes.llm, "use_llm", lambda: True)
    monkeypatch.setattr(nodes.llm, "chat_json",
                        lambda *a, **k: {"headline": "엔비디아 AI 시장 주도권 강화",
                                         "lead": "엔비디아가 시장을 주도한다", "body": "본문.", "source": "x"})
    news = [{"title": "나인앤컴퍼니 냉각", "snippet": "GPU 발열", "source": "동아일보"}]
    out = nodes._analyze(NVDA_TOPIC, NVDA_DATA, news)
    assert "주도권" not in out["headline"]
    assert "203.53달러" in out["headline"]


def test_analyze_keeps_headline_when_topic_relevant(monkeypatch):
    monkeypatch.setattr(nodes.llm, "use_llm", lambda: True)
    monkeypatch.setattr(nodes.llm, "chat_json",
                        lambda *a, **k: {"headline": "엔비디아 실적 호조",
                                         "lead": "매출 증가", "body": "본문.", "source": "x"})
    news = [{"title": "엔비디아 실적 발표", "snippet": "매출 사상 최대", "source": "동아일보"}]
    out = nodes._analyze(NVDA_TOPIC, NVDA_DATA, news)
    assert out["headline"] == "엔비디아 실적 호조"   # 관련 근거면 LLM 헤드라인 유지


def test_image_prompt_drops_body_when_topic_irrelevant(monkeypatch):
    # 무관 근거일 때 이미지 프롬프트는 LLM(body 기반) 대신 토픽 앵커 폴백을 써야 함
    called = {"llm": False}
    def _boom(*a, **k):
        called["llm"] = True
        return {"prompt": "datacenter cooling pipes and apple logo"}  # 엉뚱한 body 소재
    monkeypatch.setattr(nodes.llm, "use_llm", lambda: True)
    monkeypatch.setattr(nodes.llm, "chat_json", _boom)
    content = {"subtitle": "엔비디아", "headline": "엔비디아 203.53달러",
               "body": "나인앤컴퍼니 데이터센터 냉각과 애플 최고가"}
    p = nodes._gen_image_prompt(content, topic_relevant=False)
    assert called["llm"] is False           # LLM 미호출(body 소재 차단)
    assert "엔비디아" in p and "cooling" not in p and "apple" not in p


def test_image_prompt_uses_llm_when_topic_relevant(monkeypatch):
    monkeypatch.setattr(nodes.llm, "use_llm", lambda: True)
    monkeypatch.setattr(nodes.llm, "chat_json",
                        lambda *a, **k: {"prompt": "isometric gpu chip scene"})
    content = {"subtitle": "엔비디아", "headline": "엔비디아 실적 호조", "body": "GPU 매출 최대"}
    p = nodes._gen_image_prompt(content, topic_relevant=True)
    assert p == "isometric gpu chip scene"
