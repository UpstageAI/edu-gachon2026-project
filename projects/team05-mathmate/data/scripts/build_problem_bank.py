"""
data/scripts/build_problem_bank.py  —  문제은행 통합 구축 파이프라인

1) orca-math(HF)를 훑어 '단원 개념 정의(UNIT_GUIDE)'에 정확히 맞는 것만 선별 (단원×난이도별 상한)
2) 그림 필요 단원 + 난이도별 부족분을 Solar로 생성 (각 단원의 개념 정의를 프롬프트에 주입)
3) 단원 순서로 정렬해 data/problems.json + data/elementary_math_problems.csv 저장 (source 표시)

특징:
- 단원명만이 아니라 UNIT_GUIDE(단원별 핵심 개념·주의)를 태깅/생성에 주입해 오매핑을 줄임
  (예: "규칙과 대응"에 경우의 수 문제가 들어가는 것 방지)
- 난이도(쉬움/중간/어려움)를 단원×난이도별 목표로 균형 있게: --per-unit 30 이면 10/10/10
- '검토(scan)'와 'LLM 태깅'을 분리: orca를 셔플 스트리밍으로 많이(=골고루) 훑되,
  태깅은 목표 버킷이 찰 때까지만 하고 조기 종료(early-stop) → 검토는 늘려도 태깅 비용은 안 늘어남
- LLM 호출을 --workers 개씩 '병렬'로 실행(속도↑), 진행은 누적 개수만 한 줄 표시

실행 (프로젝트 루트, .env에 SOLAR_API_KEY):
  python data/scripts/build_problem_bank.py --grades 5 --per-unit 6 --scan 3000        # 소량 점검
  python data/scripts/build_problem_bank.py --grades 4,5,6 --per-unit 30 --scan 60000  # 많이 훑고 필요한 만큼만 태깅
  python data/scripts/build_problem_bank.py --grades 5 --per-unit 30 --scan 20000 --no-generate  # 선별만

주요 옵션:
  --scan      orca에서 '검토'할 문항 수(값쌈, 네트워크 스트리밍). 크게 줘도 됨.
  --max-tags  LLM 태깅 호출 상한(비쌈). 0이면 무제한(버킷 충족/정체 시 자동 종료).
  --seed      orca 셔플 시드. 바꾸면 다른 표본을 봄(다양성).
"""
import argparse
import csv
import json
import logging
import os
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from app.core import llm_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("app.core.llm_client").setLevel(logging.ERROR)
log = logging.getLogger("build_problem_bank")

DATASET = "kuotient/orca-math-word-problems-193k-korean"
DATA_DIR = os.path.join(ROOT, "data")
DIFFICULTIES = ["쉬움", "중간", "어려움"]

CURRICULUM = {
    4: {1: ["큰 수", "각도", "곱셈과 나눗셈", "평면도형의 이동", "막대그래프", "규칙 찾기"],
        2: ["분수의 덧셈과 뺄셈", "삼각형", "소수의 덧셈과 뺄셈", "사각형", "꺾은선그래프", "다각형"]},
    5: {1: ["자연수의 혼합 계산", "약수와 배수", "규칙과 대응", "약분과 통분", "분수의 덧셈과 뺄셈", "다각형의 둘레와 넓이"],
        2: ["수의 범위와 어림하기", "분수의 곱셈", "합동과 대칭", "소수의 곱셈", "직육면체", "평균과 가능성"]},
    6: {1: ["분수의 나눗셈", "각기둥과 각뿔", "소수의 나눗셈", "비와 비율", "여러 가지 그래프", "직육면체의 겉넓이와 부피"],
        2: ["분수의 나눗셈", "소수의 나눗셈", "공간과 입체", "비례식과 비례배분", "원의 넓이", "원기둥, 원뿔, 구"]},
}

# 단원별 핵심 개념(+ 헷갈리기 쉬운 것 명시). 태깅/생성 프롬프트에 주입한다.
UNIT_GUIDE = {
    "큰 수": "만·억·조 단위 큰 수의 자릿값, 읽고 쓰기, 뛰어 세기, 크기 비교",
    "각도": "각의 크기(도) 재기·그리기, 예각·직각·둔각, 각도의 합과 차, 삼각형·사각형 내각의 합",
    "곱셈과 나눗셈": "(세 자리)×(몇십·두 자리), (몇백몇십·세 자리)÷(몇십·두 자리) 계산과 활용 문장제",
    "평면도형의 이동": "도형을 밀기·뒤집기·돌리기 한 뒤의 모양, 무늬 만들기",
    "막대그래프": "막대그래프를 읽고 해석·그리기 (항목별 수량 비교)",
    "규칙 찾기": "수 배열·도형 배열·계산식에 숨은 '한 가지' 규칙을 찾아 다음을 예측 (두 양의 대응관계와는 다름)",
    "분수의 덧셈과 뺄셈": "분모가 같은 진분수·대분수의 덧셈·뺄셈(4학년) / 분모가 다른 진분수·대분수의 덧셈·뺄셈, 통분(5학년)",
    "삼각형": "변 길이로 이등변·정삼각형, 각 크기로 예각·직각·둔각삼각형 분류와 성질",
    "소수의 덧셈과 뺄셈": "소수 두·세 자리의 크기 비교와 덧셈·뺄셈(자릿수 맞추기)",
    "사각형": "수직과 평행, 평행선 사이의 거리, 사다리꼴·평행사변형·마름모의 성질",
    "꺾은선그래프": "꺾은선그래프를 읽고 해석·그리기 (시간에 따른 변화)",
    "다각형": "다각형과 정다각형의 뜻, 대각선의 수, 모양 만들기",
    "자연수의 혼합 계산": "+,-,×,÷와 괄호가 섞인 '자연수' 식의 계산 순서. ※ 분수·소수를 섞지 말 것",
    "약수와 배수": "약수·배수, 공약수와 최대공약수, 공배수와 최소공배수",
    "규칙과 대응": "두 양이 서로 짝지어 규칙적으로 변하는 '대응 관계'를 표로 찾고 식으로 나타내기(예: 식탁 수 □와 의자 수 △의 관계 △=□×4). 한 양이 정해지면 다른 양이 정해지는 함수적 관계. ※ 경우의 수·조합·집합(교집합·합집합)·단발성 곱셈 문제가 아님",
    "약분과 통분": "크기가 같은 분수, 약분·기약분수, 통분·공통분모, 분수와 소수의 크기 비교",
    "다각형의 둘레와 넓이": "정다각형·사각형의 둘레, 넓이 단위(1cm²·1m²·1km²), 직사각형·평행사변형·삼각형·마름모·사다리꼴의 넓이",
    "수의 범위와 어림하기": "이상·이하·초과·미만으로 수의 범위 나타내기, 올림·버림·반올림",
    "분수의 곱셈": "(분수)×(자연수), (자연수)×(분수), 진분수·대분수끼리의 곱셈",
    "합동과 대칭": "포개어지는 합동인 도형과 성질, 선대칭도형·점대칭도형. ※ 좌표평면·무리수·방정식이 아닌 '도형' 문제",
    "소수의 곱셈": "(소수)×(자연수), (자연수)×(소수), (소수)×(소수), 곱의 소수점 위치",
    "직육면체": "직육면체·정육면체의 면·모서리·꼭짓점, 겨냥도, 전개도. ※ 겉넓이·부피는 6학년",
    "평균과 가능성": "여러 자료의 평균 구하기, 일이 일어날 가능성을 말(불가능~확실)과 수(0~1)로 표현. ※ 경우의 수·순열·조합이 아님",
    "분수의 나눗셈": "(자연수)÷(자연수)를 분수로 나타내기, (분수)÷(자연수), (분수)÷(분수), (자연수)÷(분수)",
    "각기둥과 각뿔": "각기둥·각뿔의 구성요소(면·모서리·꼭짓점)와 전개도",
    "소수의 나눗셈": "(소수)÷(자연수), (자연수)÷(자연수)의 소수 몫, (소수)÷(소수), 몫을 반올림하기",
    "비와 비율": "두 수의 비(예: 3:4), 비율(기준량에 대한 비교하는 양), 백분율(%). ※ 비례식·비례배분은 별도 단원",
    "여러 가지 그래프": "그림그래프·띠그래프·원그래프를 읽고 해석·그리기",
    "직육면체의 겉넓이와 부피": "직육면체·정육면체의 겉넓이, 부피 단위(1cm³·1m³), 부피 구하기",
    "공간과 입체": "쌓기나무로 쌓은 모양을 여러 방향에서 본 모양, 쌓기나무 개수 구하기",
    "비례식과 비례배분": "비의 성질, 간단한 자연수의 비로 나타내기, 비례식(3:4=6:8) 풀기, 비례배분",
    "원의 넓이": "원주율, 원주 구하기, 원의 넓이 구하기",
    "원기둥, 원뿔, 구": "원기둥·원뿔·구의 뜻과 성질, 구성요소",
}
# 같은 단원명이 학기별로 다른 개념을 다루는 경우 (6학년 분수/소수의 나눗셈)
GUIDE_OVERRIDE = {
    (6, 1, "분수의 나눗셈"): "(자연수)÷(자연수)의 몫을 분수로 나타내기, (분수)÷(자연수)",
    (6, 2, "분수의 나눗셈"): "분모가 같거나 다른 (분수)÷(분수), (자연수)÷(분수), (대분수)÷(분수)",
    (6, 1, "소수의 나눗셈"): "(소수)÷(자연수), (자연수)÷(자연수)의 몫을 소수로, 몫의 소수점 위치",
    (6, 2, "소수의 나눗셈"): "(소수)÷(소수), 나누어떨어지지 않는 나눗셈, 몫을 반올림하여 나타내기",
}


def get_guide(g, sem, unit):
    return GUIDE_OVERRIDE.get((g, sem, unit)) or UNIT_GUIDE.get(unit, "")


FIGURE_DEPENDENT = {
    "각도", "평면도형의 이동", "삼각형", "사각형", "다각형", "막대그래프", "꺾은선그래프",
    "합동과 대칭", "직육면체", "각기둥과 각뿔", "여러 가지 그래프", "공간과 입체", "원기둥, 원뿔, 구",
}
_GUIDE_BLOCK = "\n".join(f"- {u}: {d}" for u, d in UNIT_GUIDE.items())
_RULES = ("초등 해당 학년 범위 안. 방정식·미지수 문자식·수열 공식·좌표평면·무리수(√)·음수 금지. "
          "정답은 반드시 '하나의 값'이어야 하며, 여러 개를 동시에 묻거나 '만약 ~라면' 같은 추가 질문을 문제 본문에 넣지 말 것.")

TAG_SYS = (
    "너는 초등 수학 데이터 큐레이터다. 문장제를 보고 아래 [단원 정의] 중 개념이 '정확히' 일치하는 단원으로만 태깅해 JSON만 출력한다.\n"
    "개념이 애매하거나 방정식·미지수 문자식·수열 공식·좌표평면·무리수(√)·음수에 해당하면 usable=false.\n"
    "[난이도] 쎈수학 A/B/C=쉬움/중간/어려움.\n[단원 정의]\n" + _GUIDE_BLOCK + "\n"
    '출력: {"usable":true/false,"grade":4|5|6,"semester":1|2,"unit":"위 목록의 정확한 이름","difficulty":"쉬움|중간|어려움",'
    '"problem":"...","answer":"...","solution_steps":["..."],"hint_by_level":{"1":"..","2":"..","3":".."},'
    '"next_question":".."}  ※ 힌트·유도질문에 최종 정답 금지.'
)
GEN_SYS = (
    "너는 초등 수학 문제 출제자다. 주어진 [단원]의 개념에 '정확히' 맞는 문장제를 만들어 JSON만 출력한다.\n"
    "규칙: 그림 없이 글로 풀 수 있게(도형은 치수를 글로). " + _RULES +
    " 힌트(1~3)·next_question에 최종 정답(숫자·값) 금지.\n"
    '출력: {"problems":[{"problem":"..","answer":"..","solution_steps":[".."],'
    '"hint_by_level":{"1":"..","2":"..","3":".."},"next_question":".."}]}'
)


def diff_quota(per_unit):
    base, rem = divmod(per_unit, 3)
    return {DIFFICULTIES[i]: base + (1 if i < rem else 0) for i in range(3)}


def _leak_free(rec):
    """정답이 힌트에 새면 True→False. 정답 문자열 그대로 또는 정답 수가 '단독'으로 등장할 때만 차단
    (예전엔 정답 숫자가 힌트의 다른 수와 겹치기만 해도 버려서 과도하게 탈락했음)."""
    ans = str(rec.get("answer", "")).strip()
    if not ans:
        return False
    nums = re.findall(r"\d+(?:[.,/]\d+)?", ans)   # 정답 속 수들
    for t in list(rec.get("hint_by_level", {}).values()) + [rec.get("next_question", "")]:
        if ans in t:
            return False
        for n in nums:
            if re.search(rf"(?<![\d.,/]){re.escape(n)}(?![\d.,/])", t):
                return False
    return True


def _valid(p):
    return (bool(str(p.get("problem", "")).strip()) and bool(str(p.get("answer", "")).strip())
            and all(k in p.get("hint_by_level", {}) for k in ("1", "2", "3")) and _leak_free(p))


def _record(p, g, sem, unit, diff, source):
    return {"grade": g, "semester": sem, "unit": unit, "difficulty": diff,
            "problem": str(p["problem"]).strip(), "answer": str(p["answer"]).strip(),
            "solution_steps": list(p.get("solution_steps", [])),
            "hint_by_level": {str(k): str(v) for k, v in p["hint_by_level"].items()},
            "next_question": str(p.get("next_question", "")).strip(), "source": source}


def _excel_safe(v):
    """엑셀이 분수(5/4)·비(3:4) 등을 날짜/시간으로 자동 변환하는 것 방지 → ="..."로 텍스트 고정.
    (problems.json 의 원본 값은 그대로 두고, 검수용 CSV에만 적용)."""
    s = str(v)
    if re.search(r"\d+\s*[/:\-]\s*\d+", s):
        return f'="{s}"'
    return s


# 중·고교 티가 나는 문항을 값싸게(LLM 없이) 걸러 태깅 낭비를 줄인다.
_ADVANCED = re.compile(r"√|∫|Σ|∑|방정식|부등식|함수|미지수|미분|적분|행렬|벡터|로그|log|sin|cos|tan|인수분해|이차|제곱근|시그마")


def _too_advanced(q):
    return bool(_ADVANCED.search(q))


def _progress(label, done, total, kept):
    sys.stdout.write(f"\r  {label}: {done}/{total} 처리 · 적재 {kept}개   ")
    sys.stdout.flush()


def _progress2(examined, tagged, kept):
    sys.stdout.write(f"\r  [선별] orca {examined}개 검토 · 태깅 {tagged}회 · 적재 {kept}개   ")
    sys.stdout.flush()


def select_from_orca(selectable, per_unit, scan, workers, max_tags, seed):
    """orca를 '셔플 스트리밍'하며 값싼 필터로 후보만 흘려보내고(=검토/examine),
    그 후보만 LLM 태깅한다. examine 수(scan)와 태깅 호출 수를 분리한 것이 핵심.
    → orca를 많이(=골고루) 훑어도, 태깅은 '목표 버킷이 찰 때까지'만 하고 조기 종료한다.

    종료 조건(먼저 만족하는 것):
      - 모든 목표 버킷 충족(all_full)
      - 태깅 상한(max_tags) 도달
      - 정체(STALL_LIMIT회 연속 적재 실패 = 채울 만한 건 사실상 다 참)
      - 스캔 소진(orca에서 scan개 검토 완료)
    """
    from datasets import load_dataset

    sem_map = defaultdict(list)          # (grade, unit) -> [목표 학기들]
    for g, s, u in selectable:
        sem_map[(g, u)].append(s)
    quota = diff_quota(per_unit)

    count = defaultdict(int)
    kept = []
    lock = threading.Lock()

    def all_full():
        for (g, u), sems in sem_map.items():
            for diff in DIFFICULTIES:
                if any(count[(g, s, u, diff)] < quota[diff] for s in sems):
                    return False
        return True

    def absorb(data):
        """태깅 결과를 알맞은 (학년·학기·단원·난이도) 버킷에 담는다. 담았으면 True."""
        if not (data and data.get("usable") and _valid(data)):
            return False
        try:
            g = int(data["grade"]); unit = str(data["unit"]).strip()
            sem = int(data.get("semester", 1)); diff = str(data.get("difficulty", "")).strip()
        except (KeyError, ValueError, TypeError):
            return False
        if not (g and (g, unit) in sem_map and diff in DIFFICULTIES):
            return False
        with lock:
            sems = sem_map[(g, unit)]
            order_sems = [sem] + [x for x in sems if x != sem] if sem in sems else sems
            for cs in order_sems:
                if count[(g, cs, unit, diff)] < quota[diff]:
                    kept.append(_record(data, g, cs, unit, diff, "orca"))
                    count[(g, cs, unit, diff)] += 1
                    return True
        return False

    def tag(c):
        q, a = c
        return llm_client.chat_json(TAG_SYS, f"[문제]\n{q}\n\n[원본 풀이/정답]\n{a}")

    # (1) 값싼 후보 스트림: orca를 셔플하며 최대 scan개 '검토', 필터 통과분만 흘려보냄(태깅 X)
    def candidates():
        ds = load_dataset(DATASET, split="train", streaming=True).shuffle(seed=seed, buffer_size=10000)
        examined = 0
        for row in ds:
            if examined >= scan:
                break
            examined += 1
            q = (row.get("question") or "").strip()
            a = str(row.get("answer") or "").strip()
            if q and len(q) <= 300 and any(c.isdigit() for c in a) and not _too_advanced(q):
                yield (q, a), examined

    STALL_LIMIT = max(1500, per_unit * len(selectable))   # 연속 N회 적재 실패면 사실상 다 참 → 중단
    gen = candidates()
    tagged = 0
    examined_seen = 0
    stall = 0
    stop = False

    # (2) 후보를 병렬 태깅하되, 조기 종료 조건에 걸리면 새 후보 투입을 멈춘다(sliding window).
    with ThreadPoolExecutor(max_workers=workers) as ex:
        inflight = {}
        for _ in range(workers * 4):
            item = next(gen, None)
            if item is None:
                break
            c, ex_n = item
            inflight[ex.submit(tag, c)] = ex_n

        while inflight:
            done_set, _pending = wait(list(inflight), return_when=FIRST_COMPLETED)
            for fut in done_set:
                ex_n = inflight.pop(fut)
                examined_seen = max(examined_seen, ex_n)
                try:
                    data = fut.result()
                except Exception:
                    data = None
                tagged += 1
                if absorb(data):
                    stall = 0
                else:
                    stall += 1
                if tagged % 10 == 0:
                    _progress2(examined_seen, tagged, len(kept))
                if all_full() or (max_tags and tagged >= max_tags) or stall >= STALL_LIMIT:
                    stop = True
            if stop:
                break
            for _ in range(len(done_set)):           # 계속할 때만 새 후보 보충
                item = next(gen, None)
                if item is None:
                    break
                c, ex_n = item
                inflight[ex.submit(tag, c)] = ex_n

    _progress2(examined_seen, tagged, len(kept))
    print()
    reason = ("버킷 충족" if all_full() else "태깅 상한" if (max_tags and tagged >= max_tags)
              else "정체(더 채울 게 없음)" if stall >= STALL_LIMIT else "스캔 소진")
    log.info("  선별 종료(%s): orca %d개 검토 · 태깅 %d회 · 적재 %d개", reason, examined_seen, tagged, len(kept))
    return kept, count


def generate_gaps(target_list, per_unit, have, workers):
    quota = diff_quota(per_unit)
    tasks = []
    for g, sem, unit in target_list:
        for diff in DIFFICULTIES:
            need = quota[diff] - have.get((g, sem, unit, diff), 0)
            if need > 0:
                tasks.append((g, sem, unit, diff, need))

    kept = []
    lock = threading.Lock()
    shortfalls = []
    MAX_ATTEMPTS = 12   # 목표치까지 끈질기게 top-up (큰 부족분도 채우도록 5→12)
    MAX_STALL = 4       # 연속 N회 하나도 못 건지면 포기(무한 루프 방지)

    def run(task):
        g, sem, unit, diff, need = task
        guide = get_guide(g, sem, unit)
        got, seen = [], set()
        stall = 0
        for _ in range(MAX_ATTEMPTS):
            if len(got) >= need:
                break
            k = need - len(got)
            ask = min(k + 2, 10)   # 무효·중복 탈락분을 감안해 조금 더 요청, 한 번에 최대 10개
            user = (f"학년: 초등 {g}학년 {sem}학기\n단원: {unit}\n[이 단원의 개념] {guide}\n"
                    f"난이도: {diff}\n이 개념에 정확히 맞는 서로 다른 문장제 {ask}개. "
                    f"소재와 숫자가 서로 겹치지 않게 다양하게 만들 것.")
            data = llm_client.chat_json(GEN_SYS, user)
            before = len(got)
            for p in (data.get("problems", []) if isinstance(data, dict) else []):
                if not _valid(p):
                    continue
                key = str(p["problem"]).strip()[:40]
                if key in seen:
                    continue
                seen.add(key)
                got.append(_record(p, g, sem, unit, diff, "generated"))
                if len(got) >= need:
                    break
            stall = 0 if len(got) > before else stall + 1   # 이번 시도에 하나라도 건졌는지
            if stall >= MAX_STALL:
                break
        if len(got) < need:
            with lock:
                shortfalls.append((g, sem, unit, diff, len(got), need))
        return got

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for recs in ex.map(run, tasks):
            done += 1
            with lock:
                kept.extend(recs)
            if done % 3 == 0 or done == len(tasks):
                _progress("[생성]", done, len(tasks), len(kept))
    print()
    if shortfalls:
        log.warning("  생성 목표 미달 %d개 버킷(그래도 최대한 채움):", len(shortfalls))
        for g, sem, unit, diff, got_n, need_n in shortfalls[:30]:
            log.warning("    %d-%d %s [%s]: %d/%d", g, sem, unit, diff, got_n, need_n)
    return kept


def targets(grades):
    # 같은 단원명이 학기별로 다른 개념이면(6학년 분수/소수의 나눗셈) 둘 다 별개 단원으로 둔다.
    out = []
    for g in grades:
        for sem, units in CURRICULUM.get(g, {}).items():
            for u in units:
                out.append((g, sem, u))
    return out


def _order_index():
    order, i = {}, 0
    for g in sorted(CURRICULUM):
        for sem in sorted(CURRICULUM[g]):
            for u in CURRICULUM[g][sem]:
                order[(g, sem, u)] = i
                i += 1
    return order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", default="4,5,6")
    ap.add_argument("--per-unit", type=int, default=30, help="단원별 목표(난이도 3등분). 30이면 10/10/10")
    ap.add_argument("--scan", type=int, default=30000,
                    help="orca에서 '검토'할 문항 수(값쌈). 태깅 호출 수와 별개 — 버킷이 차면 태깅은 조기 종료")
    ap.add_argument("--max-tags", type=int, default=0,
                    help="LLM 태깅 호출 상한(비쌈). 0이면 무제한(버킷 충족/정체로 자동 종료)")
    ap.add_argument("--seed", type=int, default=42, help="orca 셔플 시드(다양성 확보). 바꾸면 다른 표본을 봄")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-generate", action="store_true")
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "problems.json"))
    args = ap.parse_args()

    if not llm_client.is_enabled():
        log.error("SOLAR_API_KEY(.env) 필요."); sys.exit(1)

    grades = [int(x) for x in args.grades.split(",") if x.strip()]
    tlist = targets(grades)
    selectable = [(g, s, u) for (g, s, u) in tlist if u not in FIGURE_DEPENDENT]
    q = diff_quota(args.per_unit)
    log.info("난이도 목표(단원당): %s", q)

    log.info("Phase A: orca 선별 (검토 최대 %d개, 태깅상한 %s, 대상 %d단원, 병렬 %d, seed=%d)",
             args.scan, args.max_tags or "무제한", len(selectable), args.workers, args.seed)
    selected, count = select_from_orca(selectable, args.per_unit, args.scan, args.workers,
                                       args.max_tags or None, args.seed)

    shortfall = sum(max(0, q[d] - count.get((g, s, u, d), 0)) for g, s, u in tlist for d in DIFFICULTIES)
    log.info("선별 %d개 · 생성으로 채울 부족분 %d개", len(selected), shortfall)

    generated = []
    if not args.no_generate and shortfall:
        log.info("Phase B: 난이도별 부족분 생성 (병렬 %d)", args.workers)
        generated = generate_gaps(tlist, args.per_unit, count, args.workers)

    order = _order_index()
    didx = {d: i for i, d in enumerate(DIFFICULTIES)}
    allrecs = selected + generated
    allrecs.sort(key=lambda r: (order.get((r["grade"], r["semester"], r["unit"]), 999), didx.get(r["difficulty"], 9)))
    for i, r in enumerate(allrecs, 1):
        r["id"] = f"p_{i:04d}"

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(allrecs, f, ensure_ascii=False, indent=2)
    csv_path = os.path.join(DATA_DIR, "elementary_math_problems.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "source", "grade", "semester", "unit", "difficulty", "problem", "answer",
                    "hint1", "hint2", "hint3", "next_question"])
        for r in allrecs:
            h = r["hint_by_level"]
            w.writerow([r["id"], r["source"], r["grade"], r["semester"], r["unit"], r["difficulty"],
                        r["problem"], _excel_safe(r["answer"]), h.get("1", ""), h.get("2", ""), h.get("3", ""), r["next_question"]])

    from collections import Counter
    log.info("=== 완료: 총 %d개 (선별 %d + 생성 %d) ===", len(allrecs), len(selected), len(generated))
    log.info("source : %s", dict(Counter(r["source"] for r in allrecs)))
    log.info("난이도 : %s", dict(Counter(r["difficulty"] for r in allrecs)))

    # 단원별·난이도별 최종 개수 검증 (목표 미달 단원을 눈에 띄게 표시)
    final = Counter((r["grade"], r["semester"], r["unit"], r["difficulty"]) for r in allrecs)
    bad = 0
    log.info("--- 단원별 개수 검증(목표 %s) ---", q)
    for g, sem, unit in tlist:
        cells = [final.get((g, sem, unit, d), 0) for d in DIFFICULTIES]
        ok = all(c >= q[d] for c, d in zip(cells, DIFFICULTIES))
        if not ok:
            bad += 1
        mark = "" if ok else "  ← 미달"
        log.info("  %d-%d %-16s 쉬움 %d / 중간 %d / 어려움 %d (합 %d)%s",
                 g, sem, unit, cells[0], cells[1], cells[2], sum(cells), mark)
    log.info("목표 달성 단원 %d/%d개%s", len(tlist) - bad, len(tlist),
             " (모두 충족!)" if bad == 0 else f" · 미달 {bad}개")
    log.info("저장: %s / 검수: %s", args.out, csv_path)


if __name__ == "__main__":
    main()
