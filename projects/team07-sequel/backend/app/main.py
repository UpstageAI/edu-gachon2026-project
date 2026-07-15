"""FastAPI 앱 진입점.

이 파일은 앱을 "조립"만 한다 (미들웨어 등록, 라우터 등록). 실제 로직은
api/routes, services, db 쪽에 있으니 여기서는 흐름만 확인하면 된다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.proxy import router as proxy_router
from app.api.routes.query import router as query_router
from app.core.config import settings

app = FastAPI(title="Text2SQL Backend")

# CORS: 실제 배포된 프론트엔드 URL + 로컬 개발용 주소만 허용한다.
# 목록은 app/core/config.py의 CORS_ALLOWED_ORIGINS에서 관리 (환경변수로 덮어쓰기 가능).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 레거시 게이트웨이(POST /api/query, 자체 guardrail+DB 재실행).
app.include_router(query_router)
# agent(app/) 의 /api/v1 기능(스트림·후속질문·비용/토큰 KPI) 패스스루 프록시.
app.include_router(proxy_router)


@app.get("/health")
async def health():
    """배포 확인용 엔드포인트. 항상 200 OK만 반환.

    주의: 경로 이름을 "/healthz"가 아니라 "/health"로 쓴다.
    Cloud Run(Knative 기반)은 "/healthz" 경로를 queue-proxy 사이드카가
    자체적으로 가로채서, 우리 컨테이너까지 요청이 전달되지 않고 404가
    나는 문제가 있었다 (2026-07-09 실배포 중 확인). 그래서 이름을 바꿨다.
    """
    return {"status": "ok"}
