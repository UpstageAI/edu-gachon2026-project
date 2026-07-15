"""
데이터 소스 설정
- 재난안전데이터 공유플랫폼 (safetydata.go.kr) 3종 API
"""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.safetydata.go.kr/V2/api"

# API 3개는 각각 별도로 승인된 키를 사용함 (공용 키 아님)
DATASETS = {
    "disaster_messages": {
        "endpoint": f"{BASE_URL}/DSSP-IF-00247",
        "name": "긴급재난문자 이력",
        "service_key": os.getenv("DISASTER_MESSAGES_SERVICE_KEY"),
        "output_raw": "raw_data/disaster_messages_raw.json",
    },
    "disaster_guidelines": {
        "endpoint": f"{BASE_URL}/DSSP-IF-20589",
        "name": "재난 국민행동요령(사회재난)",
        "service_key": os.getenv("DISASTER_GUIDELINES_SERVICE_KEY"),
        "output_raw": "raw_data/disaster_guidelines_raw.json",
    },
    "disaster_guidelines_natural": {
        "endpoint": f"{BASE_URL}/DSSP-IF-20588",
        "name": "재난 국민행동요령(자연재난)",
        "service_key": os.getenv("NATURAL_DISASTER_GUIDELINES_SERVICE_KEY"),
        "output_raw": "raw_data/disaster_guidelines_natural_raw.json",
    },
    "disaster_guidelines_life": {
        "endpoint": f"{BASE_URL}/DSSP-IF-20590",
        "name": "재난 국민행동요령(생활안전)",
        "service_key": os.getenv("LIFE_SAFETY_GUIDELINES_SERVICE_KEY"),
        "output_raw": "raw_data/disaster_guidelines_life_raw.json",
    },
    "response_agencies": {
        "endpoint": f"{BASE_URL}/DSSP-IF-10086",
        "name": "재난대응기관",
        "service_key": os.getenv("RESPONSE_AGENCIES_SERVICE_KEY"),
        "output_raw": "raw_data/response_agencies_raw.json",
    },
}