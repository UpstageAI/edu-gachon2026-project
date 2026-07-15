"""
scripts/embed_foods.py
foods 테이블의 각 음식에 search_text(이름+역할+성격설명) 생성 + embedding(4096) 채우기.

- 결정 C(docs/08): LLM(solar-pro3)이 음식마다 맛·성격 한 줄을 생성해 검색 품질을 높인다.
  예: 김치찌개 → "얼큰하고 칼칼한 매운 국물" → search_text에 포함 → "얼큰한" 검색이 잘 걸림.
- ★ 개선: 음식명만이 아니라 재료(ingredients)·역할까지 LLM에 준다.
  이름만 주면 "담백/고소/칼칼" 같은 뻔한 표현만 나온다(이전 데이터셋의 한계).
  재료를 함께 주면 식감·맛·영양 성격을 구체적으로 추론해 다양한 표현이 나온다.
  예: 연두부·새우·시금치·무염버터 → "부드럽고 순한 고단백 저염 찜, 크리미한 식감"
- 사용자가 원할 때만 수동 실행하는 1회성 배치.
- 재실행 안전(재개 가능): search_text가 이미 있는 행은 건너뛴다.
  --force 주면 전부 다시 생성.

실행:
    uv run python scripts/embed_foods.py
    uv run python scripts/embed_foods.py --force        # 전부 재생성
    uv run python scripts/embed_foods.py --limit 20      # 앞 N개만(샘플 확인용)
"""

import argparse
import os

from dotenv import load_dotenv

from app.services.embedding_service import embed_passage
from app.services.supabase_client import get_client

load_dotenv()

TRAIT_PROMPT = """다음 한국 음식의 맛·식감·성격을 검색용으로 한 줄(40자 이내)로만 답하세요.
- 재료를 근거로 맛(담백/얼큰/고소/새콤 등), 식감(부드러운/바삭한/쫄깃한 등),
  영양 성격(고단백/저염/채소위주/든든한 등)을 구체적으로 표현하세요.
- 음식 이름을 다시 적지 말고, 성격 표현만 형용사·명사로 나열하세요.
- 설명·부연·따옴표·화살표(→) 없이 표현만 답하세요.
예시)
  입력: 김치찌개(재료: 김치, 돼지고기, 두부)
  출력: 얼큰하고 칼칼한 매운 국물, 든든한 돼지고기 찌개

입력: """


def summarize_ingredients(ingredients: str) -> str:
    """재료 원문에서 재료명 위주로 요약(양·단위 제거). LLM 프롬프트·검색문에 사용.

    원문 예:
        새우두부계란찜\n연두부 75g(3/4모), 칵테일새우 20g(5마리)...\n고명\n시금치 10g(3줄기)
    → 연두부, 칵테일새우, 달걀, 생크림, 설탕, 무염버터, 시금치
    """
    import re

    if not ingredients:
        return ""
    lines = ingredients.split("\n")
    # 첫 줄은 대개 요리명 반복 → 제외
    if lines:
        lines = lines[1:]
    # 구획 라벨(재료명이 아닌 것) 제거용
    label_words = ("양념", "고명", "소스", "재료", "육수", "국물", "밥", "장식", "토핑", "고물")
    names: list[str] = []
    for line in " ".join(lines).split(","):
        token = line.strip()
        if not token:
            continue
        # 불릿·구획기호(●·:-) 제거
        token = re.sub(r"^[●·•▪◦\-\s:]+", "", token)
        # ':' 뒤에 실제 재료가 오는 경우가 많음(예 "양념장 : 저염간장") → ':' 뒷부분만
        if ":" in token:
            token = token.split(":")[-1].strip()
        # 맨 앞 재료명만: 첫 숫자/괄호 이전까지, '약간' 등 꼬리 제거
        name = re.split(r"[\d(]", token, maxsplit=1)[0].strip()
        name = re.sub(r"\s*(약간|조금|적당량|소량)\s*$", "", name).strip()
        # 순수 이름 2~10자, 숫자 없음, 구획 라벨 아님
        if not (2 <= len(name) <= 10) or any(ch.isdigit() for ch in name):
            continue
        if any(w in name for w in label_words):
            continue
        names.append(name)
    # 중복 제거(순서 유지), 최대 10개
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return ", ".join(seen[:10])


def make_trait(food_name: str, ingredients_summary: str) -> str:
    """LLM으로 음식 성격 한 줄 생성. 실패 시 빈 문자열(이름+역할만으로 fallback)."""
    prompt_food = food_name
    if ingredients_summary:
        prompt_food = f"{food_name}(재료: {ingredients_summary})"
    try:
        import litellm

        r = litellm.completion(
            model="openai/" + os.getenv("LLM_MODEL", "solar-pro3"),
            messages=[{"role": "user", "content": TRAIT_PROMPT + prompt_food}],
            api_key=os.getenv("UPSTAGE_API_KEY"),
            api_base="https://api.upstage.ai/v1",
            temperature=0,
            timeout=30,  # 무한 대기 방지
            num_retries=2,
        )
        import re

        text = r.choices[0].message.content.strip().replace("\n", " ")
        # 모델이 "음식명 → 설명" 형태로 답하면 화살표 뒷부분만 취한다
        if "→" in text:
            text = text.split("→", 1)[1].strip()
        # "(재료: ...)" 프롬프트 조각을 그대로 되뱉는 경우 제거
        text = re.sub(r"\(재료:[^)]*\)", "", text)
        # 앞에 음식명이 그대로 반복되면 제거
        if text.startswith(food_name):
            text = text[len(food_name) :]
        # 남은 앞쪽 구두점·공백 정리
        text = re.sub(r"\s+", " ", text).lstrip(" :·-,").strip()
        return text[:60]
    except Exception as e:
        print(f"    [성격설명 실패 → 생략] {food_name}: {str(e)[:60]}")
        return ""


def build_search_text(food_name: str, meal_role: str, trait: str, ingredients_summary: str) -> str:
    """임베딩 입력 문장: 이름 / 역할 / 성격설명 / 주요재료.

    재료명 자체도 검색 대상에 포함시키면 "두부 들어간 거", "새우 요리" 같은
    재료 기반 검색도 의미검색으로 걸린다.
    """
    parts = [food_name, meal_role]
    if trait:
        parts.append(trait)
    if ingredients_summary:
        parts.append(ingredients_summary)
    return " / ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="search_text 있어도 전부 재생성")
    ap.add_argument("--limit", type=int, default=None, help="앞 N개만 처리(샘플)")
    args = ap.parse_args()

    client = get_client()

    # embedding(4096 벡터)은 조회하지 않는다 — 값을 다 끌어오면 응답이 거대해져
    # Supabase statement timeout(57014)이 난다. 미완료 판별은 search_text 유무로.
    rows = []
    page = 500
    start = 0
    while True:
        chunk = (
            client.table("foods")
            .select("food_id, food_name, meal_role, ingredients, search_text")
            .order("food_id")
            .range(start, start + page - 1)
            .execute()
            .data
        )
        rows.extend(chunk)
        if len(chunk) < page:
            break
        start += page

    todo = rows if args.force else [r for r in rows if not r.get("search_text")]
    if args.limit:
        todo = todo[: args.limit]

    print(f"대상 {len(todo)}개 / 전체 {len(rows)}개 (force={args.force})")

    done = 0
    for r in todo:
        ing = summarize_ingredients(r.get("ingredients") or "")
        trait = make_trait(r["food_name"], ing)
        search_text = build_search_text(r["food_name"], r["meal_role"], trait, ing)
        vec = embed_passage(search_text)
        client.table("foods").update(
            {"search_text": search_text, "embedding": vec, "updated_at": "now()"}
        ).eq("food_id", r["food_id"]).execute()
        done += 1
        if done <= 5 or done % 50 == 0:
            print(f"  [{done}/{len(todo)}] {search_text}")

    print(f"완료. {done}개 임베딩 저장.")


if __name__ == "__main__":
    main()
