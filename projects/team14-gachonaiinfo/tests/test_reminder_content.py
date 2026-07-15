"""리마인드 본문이 '요청 문장'이 아니라 RAG로 찾은 실제 일정(LLM 정리 답변)을
담는지 검증. DB/LLM은 monkeypatch로 대체해 결정적으로 테스트한다.
(자료에서 일정을 못 찾으면 예약하지 않고 안내한다.)"""

import asyncio

from langchain_core.messages import HumanMessage

import app.graph.nodes as nodes


def _state(q, pending=None):
    return {
        "messages": [HumanMessage(content=q)],
        "session_id": "test",
        "pending_action": pending,
    }


def _run(coro):
    return asyncio.run(coro)


# ── _reminder_topic_query: 요청 문장에서 주제만 추출 ──────────────────────
class TestTopicQuery:
    def test_strips_email_and_boilerplate(self):
        q = "수강신청 일정을 myid@gachon.ac.kr 로 리마인드 메일 보내줘"
        assert nodes._reminder_topic_query(q) == "수강신청 일정을"

    def test_falls_back_when_only_boilerplate(self):
        # 주제어가 없으면(이메일만) 원문(이메일 제거본)으로 폴백 — 빈 질의 방지
        out = nodes._reminder_topic_query("리마인드 해줘 a@b.com")
        assert "리마인드" in out  # 폴백이므로 보일러플레이트가 남아있음


# ── reminder_node 새 요청: RAG 일정을 본문으로 사용 ───────────────────────
class TestReminderNodeNewRequest:
    def test_no_schedule_does_not_book(self, monkeypatch):
        async def fake_fetch(_q):
            return None

        monkeypatch.setattr(nodes, "_fetch_schedule_for_reminder", fake_fetch)
        out = _run(nodes.reminder_node(_state("셔틀버스 시간표 a@b.com 로 리마인드 보내줘")))
        assert out["pending_action"] is None  # 예약 안 함
        assert "확인이 어려워" in out["messages"][-1].content

    def test_with_email_uses_rag_content_and_confirms(self, monkeypatch):
        schedule = "2학기 수강신청은 8/12~8/16이에요. 정정기간은 9/1~9/3이에요."

        async def fake_fetch(_q):
            return schedule

        monkeypatch.setattr(nodes, "_fetch_schedule_for_reminder", fake_fetch)
        out = _run(
            nodes.reminder_node(_state("수강신청 일정 hong@gachon.ac.kr 로 리마인드 보내줘"))
        )
        p = out["pending_action"]
        assert p["stage"] == "awaiting_confirm"
        assert p["content"] == schedule  # 요청 문장이 아니라 RAG 일정
        assert p["email"] == "hong@gachon.ac.kr"
        # 확인 메시지에 실제 일정이 노출되어 사용자가 검토 가능
        assert "8/12" in out["messages"][-1].content

    def test_without_email_asks_email_but_keeps_content(self, monkeypatch):
        async def fake_fetch(_q):
            return "일정 내용 요약"

        monkeypatch.setattr(nodes, "_fetch_schedule_for_reminder", fake_fetch)
        out = _run(nodes.reminder_node(_state("수강신청 일정 리마인드 해줘")))
        p = out["pending_action"]
        assert p["stage"] == "awaiting_email"
        assert p["content"] == "일정 내용 요약"


# ── _fetch_schedule_for_reminder: 가드레일/생성 로직 ──────────────────────
class TestFetchSchedule:
    def _repo(self, docs):
        class FakeRepo:
            async def search_similar(self, *a, **k):
                return docs

        return FakeRepo()

    def _llm(self, text):
        class FakeMsg:
            content = text

        class FakeLLM:
            async def ainvoke(self, _msgs):
                return FakeMsg()

        return FakeLLM()

    def test_none_when_no_docs(self, monkeypatch):
        monkeypatch.setattr(nodes, "get_rag_repository", lambda: self._repo([]))
        monkeypatch.setattr(nodes, "classify_categories", lambda _t: [])
        monkeypatch.setattr(nodes, "_is_out_of_scope", lambda _t: False)
        assert _run(nodes._fetch_schedule_for_reminder("수강신청 일정")) is None

    def test_none_when_low_score(self, monkeypatch):
        docs = [{"content": "x", "score": 0.1}]  # GUARDRAIL_MIN_SCORE(0.45) 미만
        monkeypatch.setattr(nodes, "get_rag_repository", lambda: self._repo(docs))
        monkeypatch.setattr(nodes, "classify_categories", lambda _t: [])
        monkeypatch.setattr(nodes, "_is_out_of_scope", lambda _t: False)
        assert _run(nodes._fetch_schedule_for_reminder("수강신청 일정")) is None

    def test_none_when_out_of_scope(self, monkeypatch):
        docs = [{"content": "x", "score": 0.9}]
        monkeypatch.setattr(nodes, "get_rag_repository", lambda: self._repo(docs))
        monkeypatch.setattr(nodes, "classify_categories", lambda _t: [])
        monkeypatch.setattr(nodes, "_is_out_of_scope", lambda _t: True)
        assert _run(nodes._fetch_schedule_for_reminder("셔틀버스")) is None

    def test_returns_llm_content_when_docs(self, monkeypatch):
        docs = [{"content": "수강신청 8/12~8/16", "score": 0.9}]
        monkeypatch.setattr(nodes, "get_rag_repository", lambda: self._repo(docs))
        monkeypatch.setattr(
            nodes, "get_llm", lambda: self._llm("2학기 수강신청은 8/12~8/16이에요.")
        )
        monkeypatch.setattr(nodes, "classify_categories", lambda _t: ["academic_calendar"])
        monkeypatch.setattr(nodes, "_is_out_of_scope", lambda _t: False)
        out = _run(nodes._fetch_schedule_for_reminder("수강신청 일정"))
        assert out == "2학기 수강신청은 8/12~8/16이에요."
