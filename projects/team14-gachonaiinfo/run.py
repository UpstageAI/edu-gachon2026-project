"""로컬 실행 진입점 (`python run.py`).

Windows에서는 uvicorn이 (reload/멀티워커가 아니면) 항상 ProactorEventLoop을
강제로 만들어 쓴다. psycopg 비동기 커넥션(AsyncPostgresSaver가 내부에서 씀)은
ProactorEventLoop을 지원하지 않으므로, `loop=` 옵션으로 SelectorEventLoop을
쓰는 커스텀 factory(app/loop_factory.py)를 지정해 우회한다.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        loop="app.loop_factory:selector_loop_factory",
    )
