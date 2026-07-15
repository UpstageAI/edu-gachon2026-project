import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_root_path = str(PROJECT_ROOT)
if project_root_path not in sys.path:
    sys.path.insert(0, project_root_path)

load_dotenv()

from app.services.condition_extractor import extract_conditions_llm  # noqa: E402


def main() -> None:
    examples = [
        "400kcal 이하로 계란 빼고 야채 많은 한 끼 추천해줘",
        "삼백 칼로리로 가볍게 먹고 싶어",  # 정규식이 못 잡던 한글 숫자
        "든든하게 백반으로 차려줘",
    ]

    for text in examples:
        conditions = extract_conditions_llm(text)
        print(f"입력: {text}")
        print(
            "  -> "
            f"kcal={conditions.target_kcal}, "
            f"mode={conditions.kcal_mode}, "
            f"선호={conditions.preferences}, "
            f"제외={conditions.exclude_foods}, "
            f"형태={conditions.meal_style}\n"
        )


if __name__ == "__main__":
    main()
