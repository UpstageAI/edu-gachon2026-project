"""
장바구니 물가 판단 에이전트 - 터미널 체험용 CLI
실행: .venv/Scripts/python.exe run.py
"""
import asyncio

from app.core.tracing import flush_traces, get_trace_callbacks
from app.graph import compiled_graph


async def main():
    print("=" * 50)
    print("  장바구니 물가 판단 에이전트 (Day2 Mock)")
    print("  종료: 'q' 또는 'exit' 입력")
    print("=" * 50)

    while True:
        try:
            query = input("\n질문: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if query.lower() in ("q", "exit", "quit", "종료"):
            print("종료합니다.")
            break

        if not query:
            continue

        result = await compiled_graph.ainvoke(
            {"user_query": query},
            # [2026-07-15] /chat(app/api/routes.py)만 트레이싱되고 이 CLI 경로는 빠져있었음 —
            # 같은 그래프를 타는 두 진입점 모두 추적되도록 맞춤. run_name/tag로 /chat 트래픽과 구분.
            config={
                "callbacks": get_trace_callbacks(),
                "run_name": "food-compass-cli",
                "metadata": {"langfuse_tags": ["cli"]},
            },
        )
        print(f"\n[{result.get('route', '?').upper()}]")
        print(result.get("answer", "응답 없음"))

    # 배치 전송이라 프로세스 종료 전에 마저 보내야 함 — 서버(app/api/main.py)는 FastAPI
    # shutdown 이벤트에서 처리하지만 이 CLI는 별도 종료 훅이 없어 여기서 직접 호출.
    flush_traces()


if __name__ == "__main__":
    asyncio.run(main())