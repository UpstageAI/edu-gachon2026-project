"""Windows용 uvicorn 커스텀 이벤트 루프 factory.

uvicorn은 Windows에서 `--reload`/멀티 워커가 아니면 항상 ProactorEventLoop을
강제로 만든다(uvicorn/loops/asyncio.py의 하드코딩). asyncio.set_event_loop_policy로
정책을 미리 바꿔도 uvicorn이 asyncio.run(..., loop_factory=...)에 자체 factory를
넘기기 때문에 정책이 무시된다. psycopg 비동기 커넥션(AsyncPostgresSaver)은
ProactorEventLoop을 지원하지 않으므로, uvicorn 실행 시 `loop=` 옵션으로 이
factory를 직접 지정해 SelectorEventLoop을 쓰도록 강제한다.
"""

import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
