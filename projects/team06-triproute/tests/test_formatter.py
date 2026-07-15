from app.utils.formatter import format_trip_plan_markdown


def test_format_trip_plan_markdown_contains_required_sections():
    plan = {
        "condition_summary": {
            "city": "강릉",
            "season": "가을",
            "duration": "1박 2일",
            "travel_style": ["바다", "감성 카페", "먹거리"],
            "schedule_intensity": "여유로운 일정",
            "transport_mode": "대중교통",
            "people_count": 3,
            "parser": "solar",
        },
        "daily_schedule": [
            {
                "day": "Day 1",
                "time_slot": "오전",
                "place": "안목해변",
                "place_name": "안목해변",
                "reason": "바다 여행 취향에 적합합니다.",
                "route_memo": "첫 일정으로 배치했습니다.",
            }
        ],
        "route_summary": [
            {
                "from": "안목해변",
                "to": "강릉 중앙시장",
                "distance_km": 6.2,
                "estimated_time": "약 20분",
                "transport_mode": "대중교통",
                "memo": "바다 일정 후 먹거리 코스로 이동합니다.",
            }
        ],
        "cost_summary": {
            "transport_cost": 9300,
            "food_cost": 90000,
            "cafe_cost": 45000,
            "admission_cost": 30000,
            "lodging_cost": 100000,
            "total_cost": 274300,
        },
        "warnings": [
            "대중교통 시간과 비용은 참고용 추정치입니다."
        ],
        "react_trace": [
            {
                "step": 1,
                "action": "parse_trip_request",
                "description": "Solar API로 사용자 입력을 구조화",
                "parser": "solar",
            }
        ],
    }

    markdown = format_trip_plan_markdown(plan)

    assert "## 여행 조건 요약" in markdown
    assert "## 시간대별 일정표" in markdown
    assert "## 예상 비용표" in markdown
    assert "안목해변" in markdown
    assert "274,300원" in markdown
    assert "대중교통 시간과 비용은 참고용 추정치입니다." in markdown
    assert "Agentic Workflow 실행 흐름" in markdown
    assert "parse_trip_request" in markdown