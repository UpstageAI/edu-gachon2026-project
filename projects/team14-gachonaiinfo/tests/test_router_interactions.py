"""라우터/리마인드 상호작용 회귀 테스트.

최근 병렬로 추가된 기능(리마인드 이어받기·학과 스코프·범위밖 주제·스몰토크 단락)이
한 경로(router_node)를 공유해 앞 단계가 뒤 단계를 '가리는' 얽힘을 막기 위한 결정적
테스트. DB/LLM을 타지 않는 경로(early return·규칙 분기)와 순수 함수만 검증한다.
(범위밖 주제의 실제 가드레일 발동은 검색이 필요해 Tier1 harness에서 별도 검증.)
"""

import asyncio
from datetime import datetime

from langchain_core.messages import HumanMessage

from app.graph.nodes import (
    _is_out_of_scope,
    _looks_like_smalltalk,
    router_node,
)
from app.services.reminder_time import apply_time_update


def _state(q, pending=None, admission_year=None):
    return {
        "messages": [HumanMessage(content=q)],
        "session_id": "test",
        "intent": None,
        "query": None,
        "applied_curriculum_year": None,
        "category_l1": None,
        "retrieved_docs": [],
        "tool_name": None,
        "tool_args": None,
        "tool_result": None,
        "guardrail": False,
        "contact": None,
        "admission_year": admission_year,
        "year_prompted": False,
        "pending_action": pending,
    }


def _reminder(stage, remind_at="2026-08-10T09:00:00", email=None):
    return {
        "type": "reminder",
        "stage": stage,
        "content": "수강신청 리마인드",
        "remind_at": remind_at,
        "remind_label": "2026-08-10 09:00",
        "email": email,
    }


def _route(q, pending=None):
    """router_node를 동기적으로 실행(선택한 케이스는 LLM/DB를 타지 않는다)."""
    return asyncio.run(router_node(_state(q, pending)))


class TestReminderTimeUpdate:
    """apply_time_update: 멀티턴 도중 시각/날짜 수정 — 날짜 유실 함정 방지."""

    NOW = datetime(2026, 7, 15, 10, 41)
    EX = "2026-08-10T09:00:00"  # 기존 예약: 8월 10일 09:00

    def test_time_only_keeps_date(self):
        # 시각만 주면 기존 날짜(8/10)를 보존한다(오늘로 리셋되지 않음).
        assert apply_time_update(self.EX, "9시 30분으로 해줘", now=self.NOW) == datetime(
            2026, 8, 10, 9, 30
        )

    def test_earlier_time_not_rolled_to_next_day(self):
        # 기존보다 이른 시각이어도 다음날로 넘기지 않는다.
        assert apply_time_update(self.EX, "8시로 해줘", now=self.NOW) == datetime(2026, 8, 10, 8, 0)

    def test_pm_word_applied(self):
        assert apply_time_update(self.EX, "오후 3시로 바꿔줘", now=self.NOW) == datetime(
            2026, 8, 10, 15, 0
        )

    def test_date_only_keeps_time(self):
        # 날짜만 주면 기존 시각(09:00)을 보존한다.
        assert apply_time_update(self.EX, "8월 15일로 바꿔줘", now=self.NOW) == datetime(
            2026, 8, 15, 9, 0
        )

    def test_no_time_or_date_returns_none(self):
        # 이메일/확인 답변엔 시각·날짜 표현이 없으므로 갱신 신호가 아니다.
        assert apply_time_update(self.EX, "hong@gachon.ac.kr 로 보내줘", now=self.NOW) is None
        assert apply_time_update(self.EX, "응 보내줘", now=self.NOW) is None


class TestReminderVsDepartmentScope:
    """T1: 리마인드 대기 중 '다른 학과' 언급은 이어받지 않고 학과 스코프로 보낸다."""

    def test_other_dept_breaks_out_at_email_stage(self):
        out = _route("컴퓨터공학과는 어때?", _reminder("awaiting_email"))
        assert out["intent"] == "out_of_scope"

    def test_other_dept_breaks_out_at_confirm_stage(self):
        out = _route("컴퓨터공학과 알려줘", _reminder("awaiting_confirm", email="a@x.com"))
        assert out["intent"] == "out_of_scope"

    def test_email_still_continues_reminder(self):
        # 회귀: 정상 이메일 답변은 계속 리마인드로 이어받는다.
        out = _route("hong@gachon.ac.kr 로 보내줘", _reminder("awaiting_email"))
        assert out["intent"] == "reminder"

    def test_confirm_yes_still_continues_reminder(self):
        # 회귀: 확인 단계 '응 보내줘'는 계속 리마인드로 이어받는다.
        out = _route("응 보내줘", _reminder("awaiting_confirm", email="a@x.com"))
        assert out["intent"] == "reminder"


class TestDepartmentVsOutOfScopeTopic:
    """학과 스코프와 범위밖 주제가 함께 걸릴 때의 우선순위."""

    def test_department_wins_over_topic(self):
        # "컴퓨터공학과 등록금" → 다른 학과 언급이 우선(학과 전용 안내).
        assert _route("컴퓨터공학과 등록금 얼마야?")["intent"] == "out_of_scope"

    def test_generic_dept_word_falls_through_to_topic(self):
        # "타 학과"는 일반 지시어 → 학과 스코프 아님 → 등록금(범위밖 주제)로 rag 진입.
        assert _route("타 학과 등록금 얼마야?")["intent"] == "rag"


class TestSmalltalkVsOutOfScopeTopic:
    """T2: 범위밖 주제는 스몰토크로 단락되면 안 된다(주제 가드레일 우회 방지)."""

    def test_topic_category_word_stays_rag_not_chat(self):
        # "등록금 사용법 알려줘": '사용법'이 스몰토크 신호지만 등록금(카테고리)이 먼저
        # 잡혀 rag로 간다(→ rag_node 주제 가드레일이 문의처 안내).
        assert _route("등록금 사용법 알려줘")["intent"] == "rag"

    def test_noncategory_topic_not_shortcircuited_by_smalltalk(self):
        # "셔틀 어떻게 써?": 스몰토크 신호+범위밖 주제 동시 → 스몰토크 단락 조건
        # (`smalltalk and not out_of_scope`)이 False라야 chat으로 새지 않는다.
        q = "셔틀 어떻게 써?"
        assert _looks_like_smalltalk(q) and _is_out_of_scope(q)
        assert not (_looks_like_smalltalk(q) and not _is_out_of_scope(q))

    def test_pure_smalltalk_still_shortcircuits(self):
        # 회귀: 범위밖 주제가 없는 순수 사용법 질문은 여전히 스몰토크로 단락된다.
        q = "어떻게 써?"
        assert _looks_like_smalltalk(q) and not _is_out_of_scope(q)
