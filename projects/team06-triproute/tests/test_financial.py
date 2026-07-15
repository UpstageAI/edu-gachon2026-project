import app.agents.financial as financial
from app.agents.financial import (
    _count_travel_days,
    _fetch_lodging_fee_per_night,
    _resolve_content_type_id,
    build_financial_summary,
)
from app.utils.cost_rules import build_cost_summary, estimate_admission_cost
from app.utils.transport_rules import (
    estimate_public_transport_fee,
    estimate_public_transport_time,
    estimate_transport_cost,
    recommend_vehicle_by_people,
    estimate_rental_car_cost,
)


def test_public_transport_time_is_longer_than_car_time():
    car_minutes = 20

    result = estimate_public_transport_time(car_minutes)

    assert result > car_minutes


def test_public_transport_fee_positive():
    fee = estimate_public_transport_fee(distance_km=12.0, people_count=2)

    assert fee > 0


def test_transport_cost_public_transport():
    result = estimate_transport_cost(
        transport_mode="대중교통",
        distance_km=12.0,
        car_minutes=20,
        taxi_fare=12000,
        people_count=2,
    )

    assert result["transport_mode"] == "대중교통"
    assert result["estimated_cost"] > 0
    assert result["is_estimated"] is True


def test_transport_cost_taxi_uses_taxi_fare():
    result = estimate_transport_cost(
        transport_mode="택시",
        distance_km=12.0,
        car_minutes=20,
        taxi_fare=12000,
        people_count=2,
    )

    assert result["estimated_cost"] == 12000
    assert result["is_estimated"] is False


def test_build_cost_summary_total():
    summary = build_cost_summary(
        transport_cost=12000,
        people_count=2,
        days=2,
        nights=1,
        cafe_visits=1,
    )

    assert summary["transport"] == 12000
    assert summary["total"] > summary["transport"]
    assert summary["currency"] == "KRW"



def test_recommend_vehicle_by_people():
    result = recommend_vehicle_by_people(people_count=4)

    assert result["vehicle_type"] == "중형차"
    assert result["daily_rental_fee"] == 80000


def test_rental_car_cost_by_days():
    result = estimate_rental_car_cost(
        people_count=2,
        travel_days=2,
    )

    assert result["vehicle_type"] == "소형차"
    assert result["rental_cost"] == 120000


def test_estimate_admission_cost_uses_real_fee_with_fallback():
    # 첫 번째 장소는 실제 요금(3000원), 두 번째는 요금 정보 없음(None) → 기본값 대체
    total = estimate_admission_cost(
        people_count=2,
        place_fees=[3000, None],
        default_fee_per_person=5000,
    )

    assert total == (3000 * 2) + (5000 * 2)


def test_count_travel_days_counts_distinct_days():
    daily_schedule = [
        {"day": "Day 1"}, {"day": "Day 1"}, {"day": "Day 2"},
    ]

    assert _count_travel_days(daily_schedule) == 2


def test_resolve_content_type_id_from_category():
    assert _resolve_content_type_id({"category": "숙박"}) == "32"
    assert _resolve_content_type_id({"content_type_id": "32"}) == "32"
    assert _resolve_content_type_id({}) is None


def test_fetch_lodging_fee_respects_room_capacity(monkeypatch):
    monkeypatch.setattr(
        financial,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        financial,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {
                "roombasecount": "4",
                "roommaxcount": "4",
                "roomoffseasonminfee1": "20000",
                "roomoffseasonminfee2": "25000",
            },
            {
                "roombasecount": "2",
                "roommaxcount": "2",
                "roomoffseasonminfee1": "50000",
                "roomoffseasonminfee2": "60000",
            },
        ],
    )

    place = {"content_id": "test-lodging"}

    assert _fetch_lodging_fee_per_night(place, people_count=2) == 20000
    assert _fetch_lodging_fee_per_night(place, people_count=4) == 20000
    # 딱 맞는 단일 객실이 없으면(5명) 4인실 2개(ceil(5/4)=2) × 20000원으로 근사
    assert _fetch_lodging_fee_per_night(place, people_count=5) == 40000


def test_fetch_lodging_fee_no_rooms_returns_none(monkeypatch):
    monkeypatch.setattr(
        financial,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        financial,
        "get_detail_info",
        lambda content_id, content_type_id: [],
    )

    place = {"content_id": "test-lodging-empty"}

    assert _fetch_lodging_fee_per_night(place, people_count=2) is None


def test_fetch_lodging_fee_ignores_zero_registered_as_fee(monkeypatch):
    # TourAPI에 요금이 "0"으로 등록된(실제 무료가 아니라 미기재로 보이는) 숙박이 실제로
    # 있어서, 이를 0원짜리 방으로 잘못 인정하면 숙박비 전체가 0이 되는 버그가 있었음.
    monkeypatch.setattr(
        financial,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        financial,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {
                "roombasecount": "2",
                "roommaxcount": "4",
                "roomoffseasonminfee1": "0",
                "roomoffseasonminfee2": "0",
                "roompeakseasonminfee1": "0",
                "roompeakseasonminfee2": "0",
            },
        ],
    )

    place = {"content_id": "test-lodging-zero-fee"}

    assert _fetch_lodging_fee_per_night(place, people_count=2) is None
    assert _fetch_lodging_fee_per_night(place, people_count=2, use_peak_season=True) is None


def test_fetch_lodging_fee_uses_peak_season_fee(monkeypatch):
    monkeypatch.setattr(
        financial,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        financial,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {
                "roombasecount": "2",
                "roommaxcount": "4",
                "roomoffseasonminfee1": "40000",
                "roomoffseasonminfee2": "50000",
                "roompeakseasonminfee1": "60000",
                "roompeakseasonminfee2": "70000",
            },
        ],
    )

    place = {"content_id": "test-lodging-peak"}

    assert _fetch_lodging_fee_per_night(place, people_count=2, use_peak_season=False) == 40000
    assert _fetch_lodging_fee_per_night(place, people_count=2, use_peak_season=True) == 60000


def test_build_financial_summary_uses_real_lodging_fee(monkeypatch):
    monkeypatch.setattr(
        financial,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        financial,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {
                "roombasecount": "2",
                "roommaxcount": "4",
                "roomoffseasonminfee1": "40000",
                "roomoffseasonminfee2": "50000",
            },
        ],
    )
    monkeypatch.setattr(
        financial,
        "_fetch_admission_fee",
        lambda place: None,
    )

    route_plan = {
        "route_summary": [],
        "daily_schedule": [{"day": "Day 1"}, {"day": "Day 2"}],
        "selected_places": [{"content_id": "hotel-1", "category": "숙박"}],
    }

    result = build_financial_summary(
        route_plan=route_plan,
        transport_mode="대중교통",
        people_count=2,
    )

    # 2박(3일 여행 가정 X, Day1/Day2 = 1박) * 40000원(기준 인원 이내 요금)
    assert result["lodging_cost"] == 40000