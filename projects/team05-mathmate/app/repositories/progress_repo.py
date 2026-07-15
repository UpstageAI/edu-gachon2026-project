"""학습 진척도 저장소 (Supabase progress 테이블).

핵심 KPI = '힌트 사용량'. 학생×문제 단위로 누적한다.
Supabase가 없으면(로컬/테스트) 조용히 무시하고 기록하지 않는다(앱 흐름을 막지 않음).
"""
import logging

from app.repositories import supabase_client

log = logging.getLogger(__name__)


def record_turn(student_id: str, problem_id: str, turn: dict) -> dict | None:
    """튜터 한 턴 결과(turn=graph out)를 읽어 진척도를 누적 upsert하고, 갱신된 행을 반환한다.

    turn에서 추출:
      - hint_given: 이번 턴에 힌트를 줬는가 (out['hint'] 존재)
      - hint_level: 도달한 힌트 단계
      - solved   : 최종 정답 도달 여부
    실패해도 예외를 삼켜 대화 흐름을 막지 않는다(이때는 None 반환).
    """
    client = supabase_client.get_client()
    if client is None or not student_id or not problem_id:
        return None
    try:
        hint_given = bool(turn.get("hint"))
        hint_level = int(turn.get("hint_level") or 0)
        solved = bool(turn.get("solved")) or bool((turn.get("diagnosis") or {}).get("solved"))
        revealed = bool(turn.get("revealed"))

        # 기존 행 읽어 누적(read-modify-write; 수업 데모 규모라 경쟁 무시)
        res = (client.table("progress").select("*")
               .eq("student_id", student_id).eq("problem_id", problem_id)
               .limit(1).execute())
        cur = (res.data or [{}])[0]

        # 이전에 이미 끝난(풀었거나 공개된) 문제를 다시 시작한 거라면, 힌트 단계는 0부터 다시 센다.
        # (attempts/hints_used는 그 문제에 들인 노력의 누적 총량이라 계속 쌓는다.)
        prior_concluded = bool(cur.get("solved")) or bool(cur.get("revealed"))
        prior_max_hint = 0 if prior_concluded else int(cur.get("max_hint_level", 0))

        row = {
            "student_id": student_id,
            "problem_id": problem_id,
            "attempts": int(cur.get("attempts", 0)) + 1,
            "hints_used": int(cur.get("hints_used", 0)) + (1 if hint_given else 0),
            "max_hint_level": hint_level if prior_concluded else max(prior_max_hint, hint_level),
            "solved": (False if prior_concluded else bool(cur.get("solved"))) or solved,
            "revealed": (False if prior_concluded else bool(cur.get("revealed"))) or revealed,
        }
        client.table("progress").upsert(row, on_conflict="student_id,problem_id").execute()
        return row
    except Exception as e:
        log.warning("진척도 기록 실패(무시): %s", e)
        return None


def get_hint_level(student_id: str, problem_id: str) -> int:
    """이 학생·문제에 대해 지금까지 도달한 최고 힌트 단계(기록 없으면 0).

    대화 자체는 턴마다 새로 시작(stateless)하지만, 힌트 단계는 이 값을 읽어
    이어서 진행한다 — 매 턴 LangGraph 체크포인터 없이도 "3단계까지 다 줬는지"를 알 수 있다.

    단, 이 문제가 이미 끝난 적이 있다면(풀었거나 힌트 다 쓰고 공개됐거나) 0을 반환한다 —
    안 그러면 예전에 끝난 문제를 나중에 다시 골랐을 때, 채팅창은 새로 시작한 것처럼
    보이는데 첫 마디에 곧장 정답이 공개돼버린다(이미 끝났던 기록을 그대로 이어받아서).
    """
    client = supabase_client.get_client()
    if client is None or not student_id or not problem_id:
        return 0
    try:
        res = (client.table("progress").select("max_hint_level, solved, revealed")
               .eq("student_id", student_id).eq("problem_id", problem_id)
               .limit(1).execute())
        rows = res.data or []
        if not rows:
            return 0
        row = rows[0]
        if row.get("solved") or row.get("revealed"):
            return 0
        return int(row["max_hint_level"])
    except Exception as e:
        log.warning("힌트 단계 조회 실패(0으로 간주): %s", e)
        return 0


def get_progress(student_id: str) -> list[dict]:
    """특정 학생의 문제별 진척도 목록."""
    client = supabase_client.get_client()
    if client is None:
        return []
    try:
        res = (client.table("progress").select("*")
               .eq("student_id", student_id).order("updated_at", desc=True).execute())
        return res.data or []
    except Exception as e:
        log.warning("진척도 조회 실패: %s", e)
        return []


def summary(student_id: str) -> dict:
    """학생 요약: 총 힌트 사용량·푼 문제 수 등(대시보드용)."""
    rows = get_progress(student_id)
    return {
        "student_id": student_id,
        "problems_attempted": len(rows),
        "problems_solved": sum(1 for r in rows if r.get("solved")),
        "total_hints_used": sum(int(r.get("hints_used", 0)) for r in rows),
    }
