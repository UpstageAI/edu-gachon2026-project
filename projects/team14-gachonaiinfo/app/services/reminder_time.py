"""자연어 문장에서 리마인드 발송 시각을 규칙 기반으로 추출.

RAG 문서에서 실제 학사 일정을 자동으로 찾아 연결하는 기능은 아직 없다(별도
과제). 지금은 사용자가 메시지에 직접 적은 날짜/시간 표현만 해석하며, 날짜
표현이 전혀 없으면 "지금 바로"로 보고 즉시(= 다음 스케줄러 tick) 발송한다.
"""

import re
from datetime import datetime, timedelta, timezone

# 한국 표준시(KST, UTC+9). 한국은 DST가 없어 고정 오프셋으로 안전하다.
# 배포 서버 tz가 UTC여도 사용자가 말하는 '오후 3시' 등 벽시계 시각을 KST로 해석한다.
KST = timezone(timedelta(hours=9), "KST")

_MONTH_DAY = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_N_DAYS_LATER = re.compile(r"(\d+)\s*일\s*(?:후|뒤)")
# 시각 앞 시간대 표현. '오후/저녁/밤/낮'은 PM, '오전/새벽/아침'은 AM으로 본다
# (예: "저녁 8시" → 20:00). 표현이 없으면 숫자 그대로(오전 취급).
_TIME = re.compile(r"(오전|오후|아침|저녁|밤|새벽|낮)?\s*(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?")
_PM_WORDS = {"오후", "저녁", "밤", "낮"}
_AM_WORDS = {"오전", "새벽", "아침"}
_RELATIVE_DAYS = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3}


def now_kst() -> datetime:
    """현재 시각을 KST 기준 naive datetime으로 반환.

    reminder_requests.remind_at 컬럼이 timestamp(without tz)이고 스케줄러도
    naive 비교를 하므로, 시스템 tz(서버가 UTC일 수 있음)에 흔들리지 않도록
    KST 벽시계 naive 값으로 통일한다. 예약 등록·발송 판정 모두 이 함수를 쓴다.
    """
    return datetime.now(KST).replace(tzinfo=None)


def parse_remind_at(text: str, now: datetime | None = None) -> datetime:
    base = now or now_kst()
    target_date = None

    m = _MONTH_DAY.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            target_date = base.replace(
                month=month, day=day, hour=0, minute=0, second=0, microsecond=0
            )
        except ValueError:
            target_date = None
        if target_date and target_date.date() < base.date():
            # 이미 지난 날짜면 내년으로 (예: 12월에 "1월 3일" 요청)
            target_date = target_date.replace(year=target_date.year + 1)

    if target_date is None:
        nd = _N_DAYS_LATER.search(text)
        if nd:
            target_date = (base + timedelta(days=int(nd.group(1)))).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

    if target_date is None:
        for word, delta in _RELATIVE_DAYS.items():
            if word in text:
                target_date = (base + timedelta(days=delta)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                break

    # 날짜 표현이 없어도 시각 표현이 있으면 '오늘 그 시각'을 기준으로 잡는다
    # (아래에서 이미 지난 시각이면 내일로 넘긴다). 날짜·시각 둘 다 없으면 즉시 발송.
    date_explicit = target_date is not None
    if target_date is None:
        if _TIME.search(text):
            target_date = base.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            return base  # 날짜/시각 표현 없음 -> 즉시 발송(Phase 1과 동일 동작)

    tm = _TIME.search(text)
    if tm:
        meridiem, hour, minute = tm.group(1), int(tm.group(2)), int(tm.group(3) or 0)
        if meridiem in _PM_WORDS and hour < 12:
            hour += 12
        elif meridiem in _AM_WORDS and hour == 12:
            hour = 0
        target_date = target_date.replace(hour=hour, minute=minute)
    else:
        target_date = target_date.replace(hour=9, minute=0)  # 시간 미지정 시 오전 9시

    # 날짜를 명시하지 않고 시각만 준 경우, 그 시각이 오늘 이미 지났으면 내일로.
    # (날짜를 명시했으면 사용자의 날짜 의도를 존중해 넘기지 않는다.)
    if not date_explicit and target_date <= base:
        target_date += timedelta(days=1)

    return target_date


def has_date_expr(text: str) -> bool:
    """문장에 날짜 표현(N월 N일 / N일 후 / 오늘·내일·모레·글피)이 있는지."""
    return bool(
        _MONTH_DAY.search(text)
        or _N_DAYS_LATER.search(text)
        or any(w in text for w in _RELATIVE_DAYS)
    )


def has_time_expr(text: str) -> bool:
    """문장에 시각 표현(N시 [N분])이 있는지."""
    return bool(_TIME.search(text))


def apply_time_update(existing: datetime | str, text: str, now: datetime | None = None):
    """진행 중인 리마인드의 발송 시각을, 사용자가 새로 말한 표현으로 갱신해 반환.

    멀티턴 도중 "9시 30분으로 해줘"처럼 일부만 바꾸는 경우를 위해:
    - 시각만 주면 기존 '날짜'를 보존하고 시각만 교체한다(그냥 재파싱하면 날짜가
      오늘로 리셋돼 유실되는 함정을 피한다).
    - 날짜만 주면 기존 '시각'을 보존하고 날짜만 교체한다.
    - 날짜·시각 둘 다 주면 새 값으로 통째 교체한다.
    - 시각·날짜 표현이 전혀 없으면 None(갱신 신호 아님)을 반환한다.
    """
    if isinstance(existing, str):
        existing = datetime.fromisoformat(existing)
    hd, ht = has_date_expr(text), has_time_expr(text)
    if not hd and not ht:
        return None
    parsed = parse_remind_at(text, now=now).replace(second=0, microsecond=0)
    if hd and ht:
        return parsed
    if ht:  # 시각만 → 기존 날짜 유지
        return existing.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
    # 날짜만 → 기존 시각 유지
    return parsed.replace(hour=existing.hour, minute=existing.minute, second=0, microsecond=0)
