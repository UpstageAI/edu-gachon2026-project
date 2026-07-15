import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("ratbox")


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """미처리 예외를 CORS 헤더가 붙은 500 JSON 응답으로 변환한다.

    반드시 CORSMiddleware보다 먼저 add(=CORSMiddleware의 안쪽)해야 한다.
    `@app.exception_handler(Exception)`으로 등록하면 Starlette가 이를
    ServerErrorMiddleware(CORSMiddleware보다 바깥쪽)로 보내버려 응답에 CORS
    헤더가 붙지 않고, 브라우저는 실제 500 에러를 "CORS policy" 위반으로
    오인 표시한다. 여기서 먼저 잡아 만든 응답은 CORSMiddleware를 정상적으로
    통과하며 나가므로 헤더가 붙는다.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": "서버 내부 오류가 발생했어요. 잠시 후 다시 시도해주세요."},
            )


def add_error_handling(app: FastAPI) -> None:
    app.add_middleware(UnhandledExceptionMiddleware)
