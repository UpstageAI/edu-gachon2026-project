import os
import subprocess
import sys

from langchain_core.prompts import ChatPromptTemplate
from langchain_upstage import ChatUpstage

DEFAULT_BASE_BRANCH = "main"
MAX_DIFF_CHARS = 12000
MAX_ERROR_CHARS = 500


def run_git_command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, check=True, text=True)
    return result.stdout


def get_base_branch() -> str:
    return os.getenv("GITHUB_BASE_REF") or os.getenv("BASE_BRANCH") or DEFAULT_BASE_BRANCH


def get_diff() -> str:
    base_branch = get_base_branch()
    run_git_command(["git", "fetch", "origin", base_branch])
    return run_git_command(["git", "diff", f"origin/{base_branch}...HEAD"])


def truncate_diff(diff: str) -> str:
    if len(diff) <= MAX_DIFF_CHARS:
        return diff
    return diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated]\n"


def create_review(diff: str) -> str:
    model_name = os.getenv("LLM_MODEL", "solar-pro3")
    llm = ChatUpstage(model=model_name)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a senior Python reviewer for a FastAPI/Streamlit AI agent project. "
                "Review only the provided git diff. Write concise Korean Markdown. "
                "Prioritize bugs, failing tests, security risks, and maintainability. "
                "Do not invent issues that are not visible in the diff.",
            ),
            (
                "human",
                "Review this diff:\n\n```diff\n{diff}\n```\n\n"
                "Format:\n"
                "## AI Review\n"
                "- Summary\n"
                "- Findings\n"
                "- Test Suggestions\n",
            ),
        ]
    )
    response = (prompt | llm).invoke({"diff": truncate_diff(diff)})
    return str(response.content)


def create_skipped_review(reason: str) -> str:
    return (
        "## AI Review\n"
        "- Summary: AI 리뷰를 생성하지 못했습니다.\n"
        "- Findings: 자동 리뷰 서비스 호출이 실패했지만, Code Quality와 Unit Tests 결과는 별도로 확인되었습니다.\n"
        "- Test Suggestions: 변경 범위에 맞는 로컬 테스트와 수동 리뷰를 진행해 주세요.\n\n"
        f"> Skipped: {reason}\n"
    )


def summarize_review_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if "403" in message and "Forbidden" in message:
        return (
            "Upstage API returned 403 Forbidden. Check UPSTAGE_API_KEY and LLM_MODEL permissions."
        )
    if not message:
        return exc.__class__.__name__
    return message[:MAX_ERROR_CHARS]


def main() -> int:
    if not os.getenv("UPSTAGE_API_KEY"):
        print(create_skipped_review("UPSTAGE_API_KEY is not configured."))
        return 0

    try:
        diff = get_diff()
    except subprocess.CalledProcessError as exc:
        print(f"Failed to read git diff: {exc}", file=sys.stderr)
        return 1

    if not diff.strip():
        print("No diff found for AI review.")
        return 0

    try:
        print(create_review(diff))
    except Exception as exc:
        print(create_skipped_review(summarize_review_error(exc)))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
