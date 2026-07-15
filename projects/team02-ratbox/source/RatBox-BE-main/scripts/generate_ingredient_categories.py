"""ingredients_master의 모든 재료를 LLM으로 1차 분류해 리뷰용 CSV를 만든다.

고정된 대분류가 아니라, "돼지고기카레/양파카레/고형카레 -> 카레"처럼 세부 제품명 단위로
묶는 카테고리를 만든다. 두 단계로 진행한다:
  1단계: 재료명마다 수식어(다진/냉동/국산/브랜드 등)를 제거한 핵심 제품명을 뽑는다.
         결과를 캐시 파일에 저장해, 2단계만 다시 돌릴 때 LLM 호출을 반복하지 않는다.
  2단계: 1단계에서 나온 서로 다른 표현들 중 같은 제품을 가리키는 것들을 하나의
         대표 카테고리명으로 통일한다. 배치를 나눠 부르는 한계상 한 번에 다 합쳐지지
         않으므로, 카테고리 개수가 더 줄지 않을 때까지 여러 라운드에 걸쳐 반복한다.

이 스크립트는 Supabase를 읽기만 하고 쓰지 않는다 (안전). 결과 CSV를 사람이 검토/수정한 뒤
load_ingredient_categories.py로 실제 적재한다.
"""

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.data.supabase_client import get_supabase

STAGE1_BATCH_SIZE = 40
STAGE2_BATCH_SIZE = 350
MAX_WORKERS = 4
MAX_STAGE2_ROUNDS = 2
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "ingredient_categories_review.csv"
STAGE1_CACHE_PATH = DATA_DIR / ".ingredient_base_names_cache.csv"


class _BaseNameAssignment(BaseModel):
    name: str = Field(..., description="입력받은 재료명 그대로")
    base_name: str = Field(
        ...,
        description=(
            "재료의 핵심 제품명. 다진/슬라이스/냉동/국산/유기농/브랜드명/포장단위 등 수식어는 "
            "제거하고, 같은 제품의 변형들이 같은 이름으로 모이도록 간결한 명사형으로 통일한다"
        ),
    )


class _Stage1BatchResult(BaseModel):
    assignments: list[_BaseNameAssignment]


class _CanonicalMapping(BaseModel):
    alias: str = Field(..., description="입력받은 이름 그대로")
    canonical: str = Field(..., description="같은 제품을 가리키는 이름들의 대표명")


class _Stage2BatchResult(BaseModel):
    mappings: list[_CanonicalMapping]


def fetch_all_ingredients() -> list[dict]:
    supabase = get_supabase()
    rows: list[dict] = []
    page = 0
    page_size = 1000
    while True:
        response = (
            supabase.table("ingredients_master")
            .select("id, name")
            .range(page * page_size, page * page_size + page_size - 1)
            .execute()
        )
        if not response.data:
            break
        rows.extend(response.data)
        page += 1
    return rows


def _extract_base_names(names: list[str]) -> dict[str, str]:
    prompt = (
        "다음은 요리 재료명 목록이다. 각 재료명에서 순수하게 상태/가공방식/원산지/브랜드/"
        "포장단위/판매형태를 나타내는 수식어만 제거하라. 재료·음식의 실질적인 정체성"
        "(어떤 과일/채소/육류/생선/곡물인지, 어떤 요리인지, 어떤 맛인지)을 나타내는 단어는 "
        "절대 제거하지 마라.\n\n"
        "제거해도 되는 수식어: 다진/슬라이스/채썬 같은 손질 방식, 냉동/냉장/국산/수입/유기농 "
        "같은 상태·원산지, 브랜드명, 포장단위, 그리고 '밀키트'(포장 형태를 나타낼 뿐이므로 "
        "제거하고 남은 요리명만 남긴다).\n"
        "예:\n"
        "'다진마늘' -> '마늘'\n"
        "'국산 냉동 브로콜리' -> '브로콜리'\n"
        "'갈비탕 밀키트' -> '갈비탕'\n"
        "'밀키트 닭다리살' -> '닭다리살'\n"
        "'찹스테이크밀키트' -> '찹스테이크'\n"
        "'낙곱새밀키트' -> '낙곱새'\n"
        "'떡볶이 밀키트' -> '떡볶이'\n\n"
        "절대 제거하면 안 되는 것 (재료/음식의 정체성을 나타내는 단어):\n"
        "'레몬즙' -> '레몬즙' (그대로 유지, '즙'만 남기지 않는다)\n"
        "'매실청' -> '매실청' (그대로 유지, '청'만 남기지 않는다)\n"
        "'청주' -> '청주' (그대로 유지, 다른 술 이름으로 바꾸지 않는다)\n"
        "'멸치육수' -> '멸치육수' (그대로 유지)\n"
        "'배추김치' -> '배추김치' (그대로 유지)\n"
        "'돼지고기'/'소고기'/'닭고기' -> 각각 그대로 유지 (서로 다른 재료)\n\n"
        "예외적으로, 즉석식품 중 같은 상품이 맛/재료 변형으로만 판매되는 경우만 그 변형도 "
        "제거한다 (이 예외는 아래 사례에만 한정한다): "
        "'돼지고기카레', '양파카레', '고형카레', '카레가루' -> 모두 '카레'.\n\n"
        "각 항목은 독립적으로 판단하라. 목록에 있는 다른 재료의 값이 섞여 들어가지 않도록 "
        "주의하라. 이미 수식어 없는 간단한 이름(예: '양파', '마늘')은 그대로 둔다.\n"
        f"재료 목록: {names}\n"
        "입력된 재료명 개수와 assignments 개수가 반드시 같아야 한다."
    )
    llm = get_llm().with_structured_output(_Stage1BatchResult)
    result = llm.invoke(prompt)

    base_name_by_name = {a.name: a.base_name.strip() for a in result.assignments}
    return {name: base_name_by_name.get(name, name) for name in names}


def _canonicalize_batch(aliases: list[str]) -> dict[str, str]:
    prompt = (
        "다음은 재료 카테고리 후보명 목록이다. 정확히 같은 재료/제품을 표기만 다르게 쓴 "
        "경우에만(오타, 띄어쓰기, 완전한 동의어) 하나의 대표명으로 통일하라.\n\n"
        "반드시 지켜야 할 규칙:\n"
        "- 같은 상위 단어(예: '즙', '청', '육수', '고기', '술', '국물')를 공유한다는 이유만으로 "
        "합치지 않는다. 그 상위 단어 앞에 붙은 재료/맛이 다르면 서로 다른 카테고리다.\n"
        "  예: '레몬즙'과 '매실즙'은 서로 다른 즙이므로 절대 합치지 않는다.\n"
        "  '매실청'과 '유자청'은 서로 다른 청이므로 절대 합치지 않는다.\n"
        "  '청주'와 '소주'는 서로 다른 술이므로 절대 합치지 않는다.\n"
        "  '돼지고기'/'소고기'/'닭고기'는 서로 다른 재료이므로 절대 합치지 않는다.\n"
        "  '멸치육수'/'사골육수'/'해물육수'도 서로 다른 육수이므로 절대 합치지 않는다.\n"
        "  '배추김치'/'파김치'도 서로 다른 김치이므로 절대 합치지 않는다.\n"
        "- 오직 완전한 동의어(예: '소고기'='쇠고기')이거나 순수한 표기 차이(오타, 띄어쓰기)일 "
        "때만 합친다.\n"
        "- 확신이 없으면 합치지 말고 canonical을 자기 자신으로 둔다. 지나치게 넓은 "
        "상위 개념(예: '고기', '국물', '살', '물', '즙', '청')으로 합치는 것은 절대 금지한다.\n"
        f"후보명 목록: {aliases}\n"
        "입력된 이름 개수와 mappings 개수가 반드시 같아야 한다."
    )
    llm = get_llm().with_structured_output(_Stage2BatchResult)
    result = llm.invoke(prompt)

    canonical_by_alias = {m.alias: m.canonical.strip() for m in result.mappings}
    return {alias: canonical_by_alias.get(alias, alias) for alias in aliases}


def _run_batches(items: list, batch_size: int, worker_fn) -> dict:
    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
    merged: dict = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for i, batch_result in enumerate(executor.map(worker_fn, batches)):
            merged.update(batch_result)
            print(f"  배치 {i + 1}/{len(batches)} 완료 ({len(merged)}개 처리)")
    return merged


def _extract_all_base_names(names: list[str]) -> dict[str, str]:
    if STAGE1_CACHE_PATH.exists():
        with STAGE1_CACHE_PATH.open(newline="", encoding="utf-8") as f:
            cached = {row["name"]: row["base_name"] for row in csv.DictReader(f)}
        if set(cached) == set(names):
            print(f"1단계 캐시 재사용: {STAGE1_CACHE_PATH}")
            return cached
        print("1단계 캐시가 현재 재료 목록과 달라 다시 계산한다.")

    print(f"1단계: 핵심 제품명 추출 ({STAGE1_BATCH_SIZE}개씩 배치)")
    base_name_by_name = _run_batches(names, STAGE1_BATCH_SIZE, _extract_base_names)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with STAGE1_CACHE_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "base_name"])
        writer.writeheader()
        writer.writerows({"name": n, "base_name": b} for n, b in base_name_by_name.items())

    return base_name_by_name


def _canonicalize_until_stable(base_names: list[str]) -> dict[str, str]:
    """배치 크기 제한 때문에 한 라운드로는 근접 중복이 다 안 합쳐지므로,
    카테고리 개수가 더 줄지 않을 때까지 반복한다. 같은 접미어(예: '~육수', '~김치')를
    가진 이름들이 같은 배치에 들어가도록 뒤에서부터(접미어 기준) 정렬해 묶는다."""
    composed = {name: name for name in base_names}
    current_distinct = sorted(set(base_names), key=lambda s: s[::-1])

    for round_num in range(1, MAX_STAGE2_ROUNDS + 1):
        print(f"2단계 라운드 {round_num}: 후보 {len(current_distinct)}개")
        round_mapping = _run_batches(current_distinct, STAGE2_BATCH_SIZE, _canonicalize_batch)
        composed = {name: round_mapping[canonical] for name, canonical in composed.items()}

        next_distinct = sorted(set(round_mapping.values()), key=lambda s: s[::-1])
        if len(next_distinct) == len(current_distinct):
            print(f"카테고리 개수가 더 줄지 않아 {round_num}라운드에서 종료한다.")
            break
        current_distinct = next_distinct

    return composed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ingredients_master 전체 재료를 LLM으로 제품명 단위 카테고리로 분류해 CSV 출력"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    ingredients = fetch_all_ingredients()
    names = [row["name"] for row in ingredients]
    print(f"재료 {len(ingredients)}개 조회 완료.")

    base_name_by_name = _extract_all_base_names(names)
    distinct_base_names = sorted(set(base_name_by_name.values()))
    print(f"1단계 결과: 서로 다른 제품명 {len(distinct_base_names)}개\n")

    canonical_by_base_name = _canonicalize_until_stable(distinct_base_names)
    distinct_categories = sorted(set(canonical_by_base_name.values()))
    print(f"\n2단계 결과: 최종 카테고리 {len(distinct_categories)}개")

    results = [
        {
            "ingredient_id": row["id"],
            "name": row["name"],
            "category": canonical_by_base_name[base_name_by_name[row["name"]]],
        }
        for row in ingredients
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ingredient_id", "name", "category"])
        writer.writeheader()
        writer.writerows(results)

    counts: dict[str, int] = {}
    for row in results:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    print(f"\n카테고리 {len(counts)}개, 상위 30개:")
    for category, count in sorted(counts.items(), key=lambda x: -x[1])[:30]:
        print(f"  {category}: {count}")

    print(f"\n결과를 {args.output}에 저장했다.")
    print("병합에서 놓친 근접 중복 카테고리명이 남아있을 수 있으니 검토 시 확인하라.")
    print("검토/수정 후 load_ingredient_categories.py로 적재하라.")


if __name__ == "__main__":
    main()
