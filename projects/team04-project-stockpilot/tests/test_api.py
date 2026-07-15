"""FastAPI 앱 로드 테스트. (실제 엔드포인트는 API 라우터 구현 단계에서 추가)"""
from app.main import app


def test_app_created():
    assert app.title == "StockPilot API"
