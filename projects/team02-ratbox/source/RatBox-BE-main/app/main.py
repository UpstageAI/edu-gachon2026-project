from fastapi import FastAPI

from app.api.routes.allergen import router as allergen_router
from app.api.routes.auth import router as auth_router
from app.api.routes.ingredient import router as ingredient_router
from app.api.routes.recommend import router as recommend_router
from app.api.routes.user import router as user_router
from app.api.routes.user_allergen import router as user_allergen_router
from app.api.routes.voice_query import router as voice_query_router
from app.core.cors import add_cors
from app.core.error_handling import add_error_handling
from app.core.observability import init_langfuse

OPENAPI_TAGS = [
    {"name": "auth", "description": "회원가입/로그인/토큰 재발급"},
    {"name": "users", "description": "내 정보 조회·수정, 내 알레르기 등록"},
    {"name": "allergens", "description": "알레르기 성분 마스터 조회"},
    {"name": "ingredients", "description": "재료 마스터 조회, 재료 선택 최종 확인"},
    {"name": "recommend", "description": "재료 기반 레시피 추천 (LangGraph Agent)"},
    {"name": "voice-query", "description": "조리 중 음성 질의 응답 (LangGraph Agent)"},
]

app = FastAPI(
    title="RatBox API",
    description="냉따뚜이 — 재료 기반 레시피 추천 및 대체재 안내 API",
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
)
init_langfuse()
add_error_handling(app)  # CORSMiddleware보다 먼저 add해서 안쪽(더 라우터에 가깝게) 위치시킨다.
add_cors(app)
app.include_router(auth_router)
app.include_router(allergen_router)
app.include_router(ingredient_router)
app.include_router(user_allergen_router)
app.include_router(user_router)
app.include_router(recommend_router)
app.include_router(voice_query_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
