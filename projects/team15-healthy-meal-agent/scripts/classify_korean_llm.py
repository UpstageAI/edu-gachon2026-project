"""
scripts/classify_korean_llm.py

804개 음식을 LLM으로 전수 분류: '건강한 한식 한 끼 재료로 적합한가?'
키워드로 못 잡는 양식·퓨전·디저트·정크를 이름+재료 기반으로 LLM이 판정한다.

출력: 판정을 CSV에 붙여 저장 + drop/borderline 후보를 md 리스트로 뽑아
      사람이 최종 확인(keep 되돌리기)할 수 있게 한다.

판정 라벨:
  keep       - 한식/건강한 한 끼 재료로 적합 (그대로 둠)
  drop       - 양식·퓨전·디저트·정크 → 삭제 후보
  borderline - 애매(한식화된 퓨전 등) → 사람이 결정

사용:
  uv run python scripts/classify_korean_llm.py           # 전수 분류 → 리포트
  uv run python scripts/classify_korean_llm.py --limit 30  # 샘플
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "app" / "data" / "foods_samsam.csv"
OUT_CSV = ROOT / "app" / "data" / "foods_classified.csv"
DROP_MD = ROOT / "docs" / "LLM분류_삭제후보.md"

PROMPT = """너는 '건강한 한식 한 끼 추천 서비스'의 데이터 큐레이터다.
아래 음식의 '요리 정체성'이 무엇인지 보고 판정하라.

★ 핵심 원칙: 음식의 '큰 틀(정체성)'이 한식이면 keep이다.
  한식에 서양 재료(버터·치즈·크림·올리브유·소스)가 조금 들어간 것은 keep.
  (예: 계란찜에 생크림 조금 → 여전히 계란찜이므로 keep,
       국수·수제비·냉면 → 소면이든 뭐든 한식 면요리이므로 keep,
       구이·조림·무침·나물·전·볶음·쌈·죽·국·찌개·탕 → 전부 한식 keep)

- keep: 정체성이 한식인 것. 밥·죽·국·찌개·탕·국수·면·나물·구이·조림·무침·전·볶음·쌈·김치·젓갈 등.
        한식 반찬·국·한그릇으로 상에 올릴 수 있으면 keep.
- drop: 정체성 자체가 양식/유럽/미국식인 것만.
        파스타·스파게티·리조또·그라탕·스테이크·함박·크로켓·뇨키·라비올리·라따뚜이·
        웰링턴·수프(스프)·차우더·팬케이크·타르타르·카프레제·양식샐러드·샌드위치.
        디저트·빵·과자·케이크·타르트·머핀·스콘·라떼·주스·음료.
        정크푸드(떡볶이·라면·치킨·꿔바로우 등).
- borderline: 한식화된 퓨전이라 애매한 것만(예: 김치 파스타, 불고기 타코, 샤브샤브, 탕수, 쌀국수).

의심스러우면 keep. 정체성이 명백히 양식/디저트일 때만 drop.
'재료에 버터/크림/소스가 있다'만으로 drop하지 마라 — 요리의 큰 틀을 봐라.

반드시 JSON만 답해라(설명·마크다운 없이):
{"label": "keep|drop|borderline", "reason": "한 줄 이유(20자 이내)"}

음식: """


def classify(name: str, ingredients: str) -> tuple[str, str]:
    import litellm

    q = name
    if ingredients:
        q = f"{name} (재료: {ingredients[:120]})"
    try:
        r = litellm.completion(
            model="openai/" + os.getenv("LLM_MODEL", "solar-pro3"),
            messages=[{"role": "user", "content": PROMPT + q}],
            api_key=os.getenv("UPSTAGE_API_KEY"),
            api_base="https://api.upstage.ai/v1",
            temperature=0,
            timeout=30,
            num_retries=2,
        )
        text = r.choices[0].message.content.strip()
        s, e = text.find("{"), text.rfind("}")
        obj = json.loads(text[s : e + 1])
        label = obj.get("label", "keep")
        if label not in ("keep", "drop", "borderline"):
            label = "keep"
        return label, str(obj.get("reason", ""))[:40]
    except Exception as e:
        return "keep", f"분류실패:{str(e)[:20]}"  # 실패는 보수적으로 keep


def _ing_summary(raw) -> str:
    s = str(raw or "").replace("\n", " ")
    return "" if s.lower() == "nan" else s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    df = pd.read_csv(CSV)
    if args.limit:
        df = df.head(args.limit).copy()

    labels, reasons = [], []
    n = len(df)
    for i, (_, row) in enumerate(df.iterrows(), 1):
        label, reason = classify(row["food_name"], _ing_summary(row.get("ingredients")))
        labels.append(label)
        reasons.append(reason)
        if i <= 5 or i % 50 == 0 or label != "keep":
            print(f"  [{i}/{n}] {label:10} {row['food_name']}  ({reason})")

    df["llm_label"] = labels
    df["llm_reason"] = reasons
    df.to_csv(OUT_CSV, index=False)

    drop = df[df["llm_label"] == "drop"]
    border = df[df["llm_label"] == "borderline"]
    keep = df[df["llm_label"] == "keep"]

    print(f"\n{'=' * 50}")
    print(f"keep {len(keep)} / drop {len(drop)} / borderline {len(border)}  (총 {n})")

    lines = [
        "# LLM 전수 분류 결과 — 삭제/애매 후보",
        "",
        f"총 {n}개 중 · keep {len(keep)} · **drop {len(drop)}** · borderline {len(border)}",
        "",
        "각 항목 앞 라벨을 고쳐서 최종 결정. `drop`=삭제, `keep`=살림.",
        "borderline은 기본 keep 취급(원하면 drop으로).",
        "",
        "## 🔴 DROP 후보 (LLM이 양식·디저트·정크로 판정)",
        f"총 {len(drop)}개",
    ]
    for _, r in drop.sort_values("meal_role").iterrows():
        lines.append(f"- drop  [{r['meal_role']}] {r['food_name']}  — {r['llm_reason']}")
    lines += ["", "## 🟡 BORDERLINE (한식화 퓨전 — 애매)", f"총 {len(border)}개"]
    for _, r in border.sort_values("meal_role").iterrows():
        lines.append(f"- keep  [{r['meal_role']}] {r['food_name']}  — {r['llm_reason']}")

    DROP_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n리포트: {DROP_MD}")
    print(f"분류 CSV: {OUT_CSV}")


if __name__ == "__main__":
    main()
