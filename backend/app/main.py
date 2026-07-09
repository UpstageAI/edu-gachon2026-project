"""FastAPI 앱 진입점.

이 파일은 앱을 "조립"만 한다 (미들웨어 등록, 라우터 등록). 실제 로직은
api/routes, services, db 쪽에 있으니 여기서는 흐름만 확인하면 된다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.query import router as query_router

app = FastAPI(title="Text2SQL Backend")

# CORS: 지금은 로컬 개발 중이라 모든 origin을 허용해둔다.
# 배포 시에는 실제 프론트엔드 Cloud Run URL로 반드시 좁혀야 한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 배포 시 프론트엔드 실제 URL로 제한
    allow_methods=["*"],
    allow_headers=["*"],
)

# 실제 요청 처리 로직은 api/routes/query.py에 있다.
app.include_router(query_router)


@app.get("/healthz")
async def healthz():
    """Cloud Run 헬스체크 및 배포 확인용 엔드포인트. 항상 200 OK만 반환."""
    return {"status": "ok"}
