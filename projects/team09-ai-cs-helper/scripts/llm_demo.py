"""LLM 응답 확인용 콘솔 데모.

콘솔에서 프롬프트를 입력하면 LiteLLM 프록시를 통해 답변을 받아 출력한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from app.clients.llm import ask


def main() -> int:
    load_dotenv()

    prompt = input("프롬프트> ").strip()
    if not prompt:
        print("입력된 프롬프트가 없습니다.")
        return 0

    try:
        print("\n답변:")
        print(ask(prompt))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
