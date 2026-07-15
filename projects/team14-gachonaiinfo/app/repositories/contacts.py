"""문의처/링크 정형 데이터 접근 + 질문 키워드 매칭 (가드레일 안내용).

RAG로 답을 못 찾은 질문에 대해, 질문 주제에 맞는 부서 연락처/공식 링크를
찾아 안내 문구의 근거로 제공한다. 모든 값은 contacts.json의 실제값을 사용하며
임의 생성하지 않는다.
"""

import json
import re
from functools import lru_cache

from app import config


@lru_cache(maxsize=1)
def _load() -> dict:
    path = config.STRUCTURED_DIR / "contacts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _kw_hits(query: str, keywords: list[str]) -> int:
    """질문 문자열에 포함된 키워드 개수."""
    q = query.lower()
    return sum(1 for kw in keywords if kw and kw.lower() in q)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[가-힣a-zA-Z0-9]+", text.lower()) if len(t) >= 2}


def _best_task(query: str, dept: dict) -> dict | None:
    """담당별 업무 중 질문과 토큰이 가장 많이 겹치는 항목."""
    qtokens = _tokens(query)
    best, best_score = None, 0
    for task in dept.get("담당별", []):
        score = len(qtokens & _tokens(task.get("업무", "")))
        if score > best_score:
            best, best_score = task, score
    return best


def match_contact(query: str) -> dict:
    """질문과 키워드가 가장 많이 겹치는 부서를 찾아 안내용 dict 반환.

    매칭 실패 시 기본안내(폴백)를 반환한다.
    """
    data = _load()

    best_dept, best_score = None, 0
    for dept in data["부서"]:
        s = _kw_hits(query, dept.get("키워드", []))
        if s > best_score:
            best_dept, best_score = dept, s

    links = [link for link in data["링크"] if _kw_hits(query, link.get("키워드", []))][:2]

    if best_dept is None:
        base = data.get("기본안내", {})
        return {
            "matched": False,
            "부서": None,
            "문구": base.get("문구"),
            "홈페이지": base.get("홈페이지"),
            "링크": links,
        }

    return {
        "matched": True,
        "부서": best_dept["이름"],
        "대표전화": best_dept.get("대표전화"),
        "담당": _best_task(query, best_dept),  # {"업무","전화"} | None
        "담당별": best_dept.get("담당별", []),
        "홈페이지": best_dept.get("홈페이지"),
        "출처URL": best_dept.get("출처URL"),
        "링크": links,
    }


def contact_phone(c: dict) -> str | None:
    """안내에 쓸 대표 전화번호 (담당 매칭 우선 → 대표전화)."""
    if not c or not c.get("matched"):
        return None
    담당 = c.get("담당")
    if 담당 and 담당.get("전화"):
        return 담당["전화"]
    return c.get("대표전화")


def format_contact(c: dict) -> str:
    """match_contact 결과를 LLM 그라운딩용 텍스트 블록으로 변환."""
    if not c or not c.get("matched"):
        base = (c.get("문구") if c else None) or (
            "학과사무실(인공지능학과 031-750-8668) 또는 교무처 학사지원팀(031-750-5045)으로 문의해 주세요."
        )
        lines = [base]
        for link in c.get("링크", []) if c else []:
            lines.append(f"관련 링크 - {link['이름']}: {link['URL']}")

        home = c.get("홈페이지") if c else None
        if home:
            lines.append(f"학교 홈페이지: {home}")
        return "\n".join(lines)

    lines = [f"부서: {c['부서']}"]
    담당 = c.get("담당")
    if 담당 and 담당.get("전화"):
        lines.append(f"담당({담당['업무']}): {담당['전화']}")
    elif c.get("대표전화"):
        lines.append(f"전화: {c['대표전화']}")
    else:
        # 대표전화가 없는 부서(예: 장학복지팀)는 업무별 번호를 안내
        for t in c.get("담당별", []):
            lines.append(f"- {t['업무']}: {t['전화']}")
    if c.get("홈페이지"):
        lines.append(f"홈페이지: {c['홈페이지']}")
    for link in c.get("링크", []):
        lines.append(f"관련 링크 - {link['이름']}: {link['URL']}")
    return "\n".join(lines)
