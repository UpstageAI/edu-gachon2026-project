import app.agents.route_planner as route_planner
from app.agents.route_planner import (
    _build_place_reason,
    _build_taste_text,
    _build_time_slots,
    _check_daily_density,
    _fetch_lodging_fee,
    _filter_places_within_radius,
    _haversine_km,
    _is_lodging_by_name,
    _normalize_rag_place,
    _reorder_places_for_time_slots,
    _search_lodging_place,
    _search_rag_places,
    _sort_by_prefer_local,
    _sort_by_rating_desc,
    build_incremental_route_plan,
    build_place_move_route_plan,
    build_slot_replacement_route_plan,
)


def test_build_taste_text_includes_prefer_local_phrase():
    assert "로컬" in _build_taste_text(["바다", "감성 카페"], prefer_local=True)
    assert "로컬" not in _build_taste_text(["바다", "감성 카페"], prefer_local=False)


def test_haversine_km_same_point_is_zero():
    assert _haversine_km(37.5, 128.9, 37.5, 128.9) == 0


def test_haversine_km_known_distance_seoul_busan():
    # 서울시청(37.5665, 126.9780) - 부산시청(35.1796, 129.0756), 실제 직선거리는 약 325km
    distance = _haversine_km(37.5665, 126.9780, 35.1796, 129.0756)
    assert 300 < distance < 350


def test_filter_places_within_radius_excludes_far_place():
    places = [
        {"name": "안목해변", "latitude": 37.7712, "longitude": 128.9471},
        {"name": "경포대(근처)", "latitude": 37.7960, "longitude": 128.8965},  # 약 5km
        {"name": "부산(멀리)", "latitude": 35.1796, "longitude": 129.0756},  # 약 300km+
    ]

    result = _filter_places_within_radius(places, max_distance_km=15.0)

    names = {p["name"] for p in result}
    assert "안목해변" in names
    assert "경포대(근처)" in names
    assert "부산(멀리)" not in names


def test_filter_places_within_radius_keeps_places_without_coordinates():
    places = [
        {"name": "A", "latitude": 37.7712, "longitude": 128.9471},
        {"name": "B", "latitude": None, "longitude": None},
    ]

    result = _filter_places_within_radius(places, max_distance_km=15.0)

    assert {p["name"] for p in result} == {"A", "B"}


def test_filter_places_within_radius_with_anchor_only_returns_new_matches():
    # anchor_places(이미 확정된 후보 군집)를 기준으로 related_places만 걸러야 하며,
    # 반환값에 anchor_places 자체가 다시 섞여 나오면 안 됨
    anchor_places = [
        {"name": "안목해변", "latitude": 37.7712, "longitude": 128.9471},
    ]
    candidates = [
        {"name": "경포대(근처)", "latitude": 37.7960, "longitude": 128.8965},  # 약 5km
        {"name": "부산(멀리)", "latitude": 35.1796, "longitude": 129.0756},  # 300km+
    ]

    result = _filter_places_within_radius(
        candidates,
        max_distance_km=15.0,
        anchor_places=anchor_places,
    )

    names = {p["name"] for p in result}
    assert names == {"경포대(근처)"}
    assert "안목해변" not in names


def test_sort_by_prefer_local_ascending_when_true():
    places = [
        _normalize_rag_place({"title": "A", "review_count": 500}, []),
        _normalize_rag_place({"title": "B", "review_count": 10}, []),
        _normalize_rag_place({"title": "C", "review_count": 100}, []),
    ]

    result = _sort_by_prefer_local(places, prefer_local=True)

    assert [p["name"] for p in result] == ["B", "C", "A"]


def test_sort_by_prefer_local_descending_when_false():
    places = [
        _normalize_rag_place({"title": "A", "review_count": 10}, []),
        _normalize_rag_place({"title": "B", "review_count": 500}, []),
    ]

    result = _sort_by_prefer_local(places, prefer_local=False)

    assert [p["name"] for p in result] == ["B", "A"]


def test_sort_by_prefer_local_places_missing_review_count_last():
    places = [
        _normalize_rag_place({"title": "없음"}, []),
        _normalize_rag_place({"title": "있음", "review_count": 5}, []),
    ]

    result = _sort_by_prefer_local(places, prefer_local=True)

    assert result[0]["name"] == "있음"
    assert result[1]["name"] == "없음"


def test_build_place_reason_varies_by_review_count_and_rating():
    # 리뷰수/평점이 다르면 추천 이유 문장도 달라져야 한다 (배치 전체에 동일 문구를 쓰던 버그 재발 방지)
    popular = _build_place_reason("음식점", 4.5, 1200, ["먹거리"])
    quiet = _build_place_reason("음식점", 3.8, 20, ["먹거리"])

    assert popular != quiet
    assert "1,200" in popular
    assert "4.5" in popular
    assert "인기" in popular
    assert "인기" not in quiet


def test_build_place_reason_handles_missing_signals():
    reason = _build_place_reason(None, None, None, [])

    assert "관광지" in reason
    assert "여행" in reason


def test_build_place_reason_restaurant_and_lodging_skip_taste_match_wording():
    # 숙박/음식점은 "OO 취향에 잘 맞습니다"라고 하면 억지로 끼워맞춘 것처럼 읽히니,
    # 평점/리뷰수 기반으로 자연스럽게 설명해야 하고 "취향" 언급 자체가 없어야 한다.
    restaurant_reason = _build_place_reason("음식점", 4.5, 1200, ["먹거리"])
    lodging_reason = _build_place_reason("숙박", 4.2, 50, ["힐링"])

    assert "취향" not in restaurant_reason
    assert "취향" not in lodging_reason
    assert "맛집" in restaurant_reason
    assert "숙소" in lodging_reason
    assert "1,200" in restaurant_reason
    assert "4.2" in lodging_reason


def test_normalize_rag_place_reason_differs_per_place():
    # 같은 배치에서 나온 두 장소라도 review_count/rating이 다르면 reason이 달라야 한다
    place_a = _normalize_rag_place(
        {"title": "A", "category": "음식점", "rating": 4.7, "review_count": 900},
        ["먹거리"],
    )
    place_b = _normalize_rag_place(
        {"title": "B", "category": "카페", "rating": 4.1, "review_count": 15},
        ["먹거리"],
    )

    assert place_a["reason"] != place_b["reason"]
    assert "900" in place_a["reason"]
    assert "15" in place_b["reason"]


def test_reorder_places_for_time_slots_prioritizes_restaurant_for_meal_slot():
    time_slots = [("Day 1", "오전"), ("Day 1", "점심"), ("Day 1", "오후")]
    places = [
        {"name": "관광지1", "category": "관광지"},
        {"name": "관광지2", "category": "관광지"},
        {"name": "맛집", "category": "음식점"},
    ]

    result = _reorder_places_for_time_slots(places, time_slots)

    assert len(result) == len(places)
    assert result[1]["category"] == "음식점"
    assert {p["name"] for p in result} == {"관광지1", "관광지2", "맛집"}


def test_reorder_places_for_time_slots_no_restaurant_keeps_all_places():
    time_slots = [("Day 1", "오전"), ("Day 1", "점심"), ("Day 1", "오후")]
    places = [
        {"name": "관광지1", "category": "관광지"},
        {"name": "관광지2", "category": "문화시설"},
        {"name": "관광지3", "category": None},
    ]

    result = _reorder_places_for_time_slots(places, time_slots)

    assert len(result) == len(places)
    assert {p["name"] for p in result} == {"관광지1", "관광지2", "관광지3"}


def test_reorder_places_for_time_slots_extra_restaurants_fill_remaining_slots():
    # 음식점 후보가 식사 시간대(1개)보다 많으면, 남는 음식점은 버려지지 않고 다른 슬롯에 배치되어야 한다
    time_slots = [("Day 1", "오전"), ("Day 1", "점심")]
    places = [
        {"name": "맛집1", "category": "음식점"},
        {"name": "맛집2", "category": "음식점"},
    ]

    result = _reorder_places_for_time_slots(places, time_slots)

    assert len(result) == 2
    assert {p["name"] for p in result} == {"맛집1", "맛집2"}


def test_build_route_plan_uses_rag_result_when_available(monkeypatch):
    fake_results = [
        {
            "content_id": "1",
            "title": "테스트 관광지",
            "address": "강원특별자치도 강릉시",
            "rating": 4.5,
            "review_count": 100,
            "category": "관광지",
        }
    ]

    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: fake_results,
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9",
            "mapy": "37.7",
            "lDongRegnCd": "51",
            "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시",
        },
    )
    monkeypatch.setattr(
        route_planner,
        "get_route",
        lambda origin, destination: {},
    )
    monkeypatch.setattr(
        route_planner,
        "summarize_route",
        lambda route: {
            "distance_km": 1.0,
            "duration_min": 10,
            "taxi_fare": 5000,
            "toll_fare": 0,
        },
    )
    monkeypatch.setattr(
        route_planner,
        "get_course_content_ids",
        lambda city, **kwargs: [],
    )

    result = route_planner.build_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "여유로운 일정",
        },
        transport_mode="대중교통",
        people_count=2,
    )

    assert result["data_source"] == "rag"
    assert len(result["rag_ranked_places"]) == 1
    assert result["rag_ranked_places"][0]["review_count"] == 100
    assert result["selected_places"][0]["latitude"] == 37.7


def test_search_course_related_places_matches_selected_place(monkeypatch):
    candidate_places = [{"content_id": "127722", "name": "안목해변"}]

    monkeypatch.setattr(
        route_planner,
        "get_course_content_ids",
        lambda city, **kwargs: ["2721490"],
    )
    # 실제 디스크 캐시(data/cache/)를 안 건드리도록 캐싱을 우회하고 fetch_fn을 바로 호출하게 함
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {"subcontentid": "127722", "subname": "안목해변"},
            {"subcontentid": "128758", "subname": "정동진"},
            {"subcontentid": "585522", "subname": "정동진해변"},
        ],
    )

    related_places, warnings = route_planner._search_course_related_places(
        candidate_places=candidate_places,
        city="강릉",
        max_related_places=5,
    )

    assert not warnings
    assert {p["name"] for p in related_places} == {"정동진", "정동진해변"}


def test_search_course_related_places_no_match_returns_empty(monkeypatch):
    candidate_places = [{"content_id": "999999", "name": "매칭 안 되는 장소"}]

    monkeypatch.setattr(
        route_planner,
        "get_course_content_ids",
        lambda city, **kwargs: ["2721490"],
    )
    # 실제 디스크 캐시(data/cache/)를 안 건드리도록 캐싱을 우회하고 fetch_fn을 바로 호출하게 함
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {"subcontentid": "127722", "subname": "안목해변"},
        ],
    )

    related_places, warnings = route_planner._search_course_related_places(
        candidate_places=candidate_places,
        city="강릉",
        max_related_places=5,
    )

    assert related_places == []
    assert not warnings


def test_search_course_related_places_excludes_far_subnum(monkeypatch):
    # 5일 코스 가정: 매칭된 장소(index 2)에서 COURSE_NEARBY_WINDOW(2)를 넘는 index 5, 6은
    # 다른 날짜 구간일 가능성이 높으므로 추천 대상에서 빠져야 함
    candidate_places = [{"content_id": "2", "name": "매칭 장소"}]

    monkeypatch.setattr(
        route_planner,
        "get_course_content_ids",
        lambda city, **kwargs: ["course-1"],
    )
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {"subcontentid": "0", "subname": "1일차-1"},
            {"subcontentid": "1", "subname": "1일차-2"},
            {"subcontentid": "2", "subname": "매칭 장소"},
            {"subcontentid": "3", "subname": "2일차-1"},
            {"subcontentid": "4", "subname": "2일차-2"},
            {"subcontentid": "5", "subname": "4일차-1"},
            {"subcontentid": "6", "subname": "5일차-1"},
        ],
    )

    related_places, warnings = route_planner._search_course_related_places(
        candidate_places=candidate_places,
        city="강릉",
        max_related_places=10,
    )

    assert not warnings
    names = {p["name"] for p in related_places}
    assert names == {"1일차-1", "1일차-2", "2일차-1", "2일차-2"}
    assert "4일차-1" not in names
    assert "5일차-1" not in names


def test_build_time_slots_drops_evening_in_winter():
    normal = _build_time_slots(1, "여유로운 일정", season="여름")
    winter = _build_time_slots(1, "여유로운 일정", season="겨울")

    assert ("Day 1", "저녁") in normal
    assert ("Day 1", "저녁") not in winter
    assert len(winter) < len(normal)


def test_build_time_slots_packed_schedule_gets_extra_attraction_slot():
    # 빡빡한 일정만 "늦은 오후" 관광지 슬롯이 추가로 붙어야 한다 (하루 관광지 3개)
    relaxed = _build_time_slots(1, "여유로운 일정", season="여름")
    normal = _build_time_slots(1, "보통", season="여름")
    packed = _build_time_slots(1, "빡빡한 일정", season="여름")

    assert ("Day 1", "늦은 오후") not in relaxed
    assert ("Day 1", "늦은 오후") not in normal
    assert ("Day 1", "늦은 오후") in packed
    assert len(packed) == len(normal) + 1


def test_build_time_slots_always_includes_lunch_regardless_of_intensity():
    # 기존에는 여유로운 일정에 점심 슬롯이 아예 없었는데, 이제는 강도와 무관하게 항상 포함해야 한다
    relaxed = _build_time_slots(1, "여유로운 일정", season="여름")
    packed = _build_time_slots(1, "빡빡한 일정", season="여름")

    assert ("Day 1", "점심") in relaxed
    assert ("Day 1", "점심") in packed


def test_build_time_slots_last_day_drops_dinner_but_keeps_lunch():
    slots = _build_time_slots(2, "빡빡한 일정", season="여름")

    assert ("Day 1", "저녁") in slots
    assert ("Day 2", "저녁") not in slots
    assert ("Day 2", "점심") in slots


def test_build_time_slots_season_default_unaffected():
    default_slots = _build_time_slots(1, "여유로운 일정")
    summer_slots = _build_time_slots(1, "여유로운 일정", season="여름")

    assert default_slots == summer_slots


def test_check_daily_density_warns_when_over_relaxed_limit():
    daily_schedule = [
        {"day": "Day 1", "place": "A"},
        {"day": "Day 1", "place": "B"},
    ]
    route_summary = [{"estimated_time_minutes": 200}]  # 180분 기준 초과

    warnings = _check_daily_density(daily_schedule, route_summary, "여유로운 일정")

    assert len(warnings) == 1
    assert "Day 1" in warnings[0]


def test_check_daily_density_no_warning_within_limit():
    daily_schedule = [
        {"day": "Day 1", "place": "A"},
        {"day": "Day 1", "place": "B"},
    ]
    route_summary = [{"estimated_time_minutes": 30}]

    warnings = _check_daily_density(daily_schedule, route_summary, "여유로운 일정")

    assert warnings == []


def test_check_daily_density_packed_has_higher_threshold():
    daily_schedule = [
        {"day": "Day 1", "place": "A"},
        {"day": "Day 1", "place": "B"},
    ]
    route_summary = [{"estimated_time_minutes": 200}]  # 여유 기준(180)은 넘지만 빡빡 기준(300)은 안 넘음

    relaxed_warnings = _check_daily_density(daily_schedule, route_summary, "여유로운 일정")
    packed_warnings = _check_daily_density(daily_schedule, route_summary, "빡빡한 일정")

    assert len(relaxed_warnings) == 1
    assert packed_warnings == []


def test_sort_by_rating_desc_places_missing_rating_last():
    places = [
        _normalize_rag_place({"title": "없음"}, []),
        _normalize_rag_place({"title": "5점", "rating": 5}, []),
        _normalize_rag_place({"title": "3점", "rating": 3}, []),
    ]

    result = _sort_by_rating_desc(places)

    assert [p["name"] for p in result] == ["5점", "3점", "없음"]


def test_fetch_lodging_fee_ignores_zero_registered_fee(monkeypatch):
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {"roommaxcount": "2", "roomoffseasonminfee1": "0"},
            {"roommaxcount": "2", "roomoffseasonminfee1": "30000"},
        ],
    )

    assert _fetch_lodging_fee("test-content-id", people_count=2, use_peak_season=False) == 30000


def test_search_lodging_place_picks_highest_rating_by_default(monkeypatch):
    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [
            {
                "content_id": "a", "title": "A호텔", "category": "숙박",
                "rating": 3, "review_count": 10, "address": "강원특별자치도 강릉시",
            },
            {
                "content_id": "b", "title": "B호텔", "category": "숙박",
                "rating": 5, "review_count": 20, "address": "강원특별자치도 강릉시",
            },
        ],
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7",
            "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시", "contenttypeid": "32",
        },
    )
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: [],  # 둘 다 요금 정보 없음 -> rating 기준으로만 판단
    )

    anchor_places = [{"latitude": 37.7, "longitude": 128.9}]

    result = _search_lodging_place(city="강릉", anchor_places=anchor_places)

    assert result["name"] == "B호텔"


def test_search_lodging_place_prefers_candidate_with_real_fee_data(monkeypatch):
    # B호텔이 평점은 더 높지만 요금 데이터가 없고, A호텔은 평점은 낮아도 실제 요금이 있음
    # -> Financial Agent가 추정치 대신 실측값을 쓸 수 있도록 A호텔을 골라야 함
    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [
            {
                "content_id": "a", "title": "A호텔", "category": "숙박",
                "rating": 3, "review_count": 10, "address": "강원특별자치도 강릉시",
            },
            {
                "content_id": "b", "title": "B호텔", "category": "숙박",
                "rating": 5, "review_count": 20, "address": "강원특별자치도 강릉시",
            },
        ],
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7",
            "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시", "contenttypeid": "32",
        },
    )
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: (
            [{"roommaxcount": "2", "roomoffseasonminfee1": "50000"}] if content_id == "a"
            else []  # B호텔은 요금 정보 없음
        ),
    )

    anchor_places = [{"latitude": 37.7, "longitude": 128.9}]

    result = _search_lodging_place(city="강릉", anchor_places=anchor_places)

    assert result["name"] == "A호텔"


def test_search_lodging_place_picks_cheapest_when_prefer_budget(monkeypatch):
    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [
            {
                "content_id": "a", "title": "A호텔", "category": "숙박",
                "rating": 5, "review_count": 10, "address": "강원특별자치도 강릉시",
            },
            {
                "content_id": "b", "title": "B호텔", "category": "숙박",
                "rating": 3, "review_count": 20, "address": "강원특별자치도 강릉시",
            },
        ],
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7",
            "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시", "contenttypeid": "32",
        },
    )
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: (
            [{"roommaxcount": "2", "roomoffseasonminfee1": "80000"}] if content_id == "a"
            else [{"roommaxcount": "2", "roomoffseasonminfee1": "30000"}]
        ),
    )

    anchor_places = [{"latitude": 37.7, "longitude": 128.9}]

    result = _search_lodging_place(
        city="강릉",
        anchor_places=anchor_places,
        prefer_budget=True,
    )

    # rating은 A가 더 높지만, prefer_budget이면 실제 요금이 더 저렴한 B를 골라야 함
    assert result["name"] == "B호텔"


def _fake_previous_result():
    """1박 2일(Day 1~2) 여행이 이미 확정된 previous_result를 흉내낸다."""
    return {
        "condition_summary": {"city": "강릉", "duration": "1박 2일", "data_source": "rag"},
        "daily_schedule": [
            {
                "day": "Day 1", "time_slot": "오전", "place": "장소A", "place_name": "장소A",
                "reason": "", "route_memo": "", "address": "", "image_url": "",
                "latitude": 37.70, "longitude": 128.90, "content_id": "1",
                "source": "rag", "category": "관광지", "content_type_id": None,
            },
            {
                "day": "Day 1", "time_slot": "체크인", "place": "강릉호텔", "place_name": "강릉호텔",
                "reason": "", "route_memo": "", "address": "", "image_url": "",
                "latitude": 37.71, "longitude": 128.91, "content_id": "10",
                "source": "rag", "category": "숙박", "content_type_id": "32",
            },
            {
                "day": "Day 2", "time_slot": "오전", "place": "장소B", "place_name": "장소B",
                "reason": "", "route_memo": "", "address": "", "image_url": "",
                "latitude": 37.72, "longitude": 128.92, "content_id": "2",
                "source": "rag", "category": "관광지", "content_type_id": None,
            },
        ],
        "route_summary": [
            {"from": "장소A", "to": "강릉호텔", "estimated_time": "약 5분", "estimated_time_minutes": 5},
            {"from": "강릉호텔", "to": "장소B", "estimated_time": "약 10분", "estimated_time_minutes": 10},
        ],
    }


def test_build_incremental_route_plan_appends_only_new_days(monkeypatch):
    new_place = {
        "name": "장소C", "title": "장소C", "content_id": "3", "address": "",
        "longitude": 128.93, "latitude": 37.73, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }

    monkeypatch.setattr(route_planner, "_search_rag_places", lambda **kwargs: [new_place])
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)
    monkeypatch.setattr(route_planner, "_search_restaurant_places", lambda **kwargs: [])
    monkeypatch.setattr(
        route_planner,
        "_build_real_routes",
        lambda selected_places, transport_mode: (
            [
                {
                    "from": selected_places[i]["name"], "to": selected_places[i + 1]["name"],
                    "estimated_time": "약 8분", "estimated_time_minutes": 8,
                }
                for i in range(len(selected_places) - 1)
            ],
            [],
        ),
    )

    previous_result = _fake_previous_result()

    result = build_incremental_route_plan(
        parsed={
            "city": "강릉",
            "duration": "2박 3일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "보통",
        },
        transport_mode="대중교통",
        people_count=2,
        previous_result=previous_result,
        previous_days=2,
    )

    daily_schedule = result["daily_schedule"]
    # 기존 Day 1/Day 2 엔트리는 그대로 앞부분에 남아있어야 한다
    assert daily_schedule[:3] == previous_result["daily_schedule"]
    # 늘어난 Day 3만 새로 추가됨
    new_entries = daily_schedule[3:]
    assert new_entries
    assert all(entry["day"] == "Day 3" for entry in new_entries)
    assert new_entries[0]["place_name"] == "장소C"
    # 첫 새 장소는 전체 여행의 "첫 방문"이 아니라 기존 마지막 장소에서 이어진 것임을 안내해야 함
    assert "장소B" in new_entries[0]["route_memo"]

    # 기존 동선 뒤에 연결 구간 + 새 구간이 이어붙어야 한다
    assert len(result["route_summary"]) == len(previous_result["route_summary"]) + 1

    # Financial Agent가 전체 비용을 다시 계산할 수 있도록 옛 장소도 selected_places에 포함돼야 함
    selected_names = {p["name"] for p in result["selected_places"]}
    assert {"장소A", "강릉호텔", "장소B", "장소C"} <= selected_names

    # 기존 숙박 정보(카테고리 포함)가 재구성되어야 늘어난 박수만큼 숙박비가 실측 유지됨
    assert result["lodging_place"]["category"] == "숙박"
    assert result["lodging_place"]["content_id"] == "10"


def test_build_incremental_route_plan_excludes_places_already_in_schedule(monkeypatch):
    duplicate_place = {
        "name": "장소A", "title": "장소A", "content_id": "1", "address": "",
        "longitude": 128.90, "latitude": 37.70, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }
    fresh_place = {
        "name": "장소D", "title": "장소D", "content_id": "4", "address": "",
        "longitude": 128.94, "latitude": 37.74, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }

    monkeypatch.setattr(
        route_planner,
        "_search_rag_places",
        lambda **kwargs: [duplicate_place, fresh_place],
    )
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)
    monkeypatch.setattr(route_planner, "_search_restaurant_places", lambda **kwargs: [])
    monkeypatch.setattr(
        route_planner,
        "_build_real_routes",
        lambda selected_places, transport_mode: ([], []),
    )

    result = build_incremental_route_plan(
        parsed={
            "city": "강릉",
            "duration": "2박 3일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "보통",
        },
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        previous_days=2,
    )

    new_place_names = {entry["place_name"] for entry in result["daily_schedule"][3:]}
    assert "장소A" not in new_place_names
    assert "장소D" in new_place_names


def test_build_slot_replacement_route_plan_replaces_only_target_slot(monkeypatch):
    new_place = {
        "name": "장소E", "title": "장소E", "content_id": "5", "address": "",
        "longitude": 128.93, "latitude": 37.73, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }

    monkeypatch.setattr(route_planner, "_search_rag_places", lambda **kwargs: [new_place])
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)
    monkeypatch.setattr(
        route_planner,
        "_build_real_routes",
        lambda selected_places, transport_mode: (
            [
                {
                    "from": selected_places[i]["name"], "to": selected_places[i + 1]["name"],
                    "estimated_time": "약 12분", "estimated_time_minutes": 12,
                }
                for i in range(len(selected_places) - 1)
            ],
            [],
        ),
    )

    previous_result = _fake_previous_result()

    result = build_slot_replacement_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "보통",
        },
        transport_mode="대중교통",
        people_count=2,
        previous_result=previous_result,
        target_day=2,
        target_time_slot="오전",
    )

    daily_schedule = result["daily_schedule"]
    # Day 1(오전/체크인)은 손대지 않고 그대로 남아있어야 한다
    assert daily_schedule[:2] == previous_result["daily_schedule"][:2]
    # Day 2 오전만 새 장소로 교체됨
    assert daily_schedule[2]["place_name"] == "장소E"
    assert daily_schedule[2]["day"] == "Day 2"
    assert daily_schedule[2]["time_slot"] == "오전"
    # 교체된 슬롯으로 들어오는 동선(강릉호텔 -> 장소E)만 갱신되고, 다른 구간은 그대로
    assert result["route_summary"][0] == previous_result["route_summary"][0]
    assert result["route_summary"][1]["to"] == "장소E"
    assert len(result["route_summary"]) == len(previous_result["route_summary"])

    selected_names = {p["name"] for p in result["selected_places"]}
    assert selected_names == {"장소A", "강릉호텔", "장소E"}
    assert any("교체했습니다" in w for w in result["warnings"])


def test_build_slot_replacement_route_plan_excludes_duplicate_and_lodging_slot(monkeypatch):
    duplicate_place = {
        "name": "장소A", "title": "장소A", "content_id": "1", "address": "",
        "longitude": 128.90, "latitude": 37.70, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }
    fresh_place = {
        "name": "장소F", "title": "장소F", "content_id": "6", "address": "",
        "longitude": 128.93, "latitude": 37.73, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }

    monkeypatch.setattr(
        route_planner, "_search_rag_places", lambda **kwargs: [duplicate_place, fresh_place]
    )
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)
    monkeypatch.setattr(
        route_planner,
        "_build_real_routes",
        lambda selected_places, transport_mode: ([], []),
    )

    result = build_slot_replacement_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "보통",
        },
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        target_day=2,
        target_time_slot="오전",
    )

    # 이미 일정에 있는 "장소A"는 제외되고, 새 장소만 선택돼야 한다
    assert result["daily_schedule"][2]["place_name"] == "장소F"


def test_build_slot_replacement_route_plan_skips_lodging_checkin_slot():
    result = build_slot_replacement_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "보통",
        },
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        target_day=1,
        target_time_slot="체크인",
    )

    # 숙박 슬롯 교체는 지원하지 않으므로 기존 일정을 그대로 유지해야 한다
    assert result["daily_schedule"] == _fake_previous_result()["daily_schedule"]
    assert any("체크인" in w for w in result["warnings"])


def test_is_lodging_by_name_detects_caravan_and_glamping():
    assert _is_lodging_by_name("강릉 금진리321카라반")
    assert _is_lodging_by_name("OO글램핑")
    assert _is_lodging_by_name("강릉경포카라반파크")
    assert not _is_lodging_by_name("경포해변 서핑 캠프")


def test_search_rag_places_excludes_caravan_tagged_as_leports(monkeypatch):
    # TourAPI가 카라반/글램핑/캠핑장을 "레포츠"로 잘못 등록해둔 경우가 실제로 있어서,
    # category만으로는 못 거르고 이름으로도 걸러야 한다(실제 DB에서 확인된 케이스).
    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [
            {
                "content_id": "1", "title": "강릉 금진리321카라반", "category": "레포츠",
                "address": "강원특별자치도 강릉시",
            },
            {
                "content_id": "2", "title": "안목해변", "category": "관광지",
                "address": "강원특별자치도 강릉시",
            },
        ],
    )

    places = _search_rag_places(
        city="강릉", travel_style=["바다"], prefer_local=False, max_places=5
    )

    names = {p["name"] for p in places}
    assert "안목해변" in names
    assert "강릉 금진리321카라반" not in names


def test_search_lodging_place_includes_caravan_tagged_as_leports(monkeypatch):
    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [
            {
                "content_id": "c", "title": "강릉경포카라반파크", "category": "레포츠",
                "rating": 4.5, "review_count": 30, "address": "강원특별자치도 강릉시",
            },
        ],
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7",
            "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시", "contenttypeid": "28",
        },
    )
    monkeypatch.setattr(
        route_planner,
        "cached_call",
        lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn(),
    )
    monkeypatch.setattr(
        route_planner, "get_detail_info", lambda content_id, content_type_id: []
    )

    anchor_places = [{"latitude": 37.7, "longitude": 128.9}]

    result = _search_lodging_place(city="강릉", anchor_places=anchor_places)

    # category가 "레포츠"인데도 이름으로 숙박 후보로 선택돼야 한다
    assert result is not None
    assert result["name"] == "강릉경포카라반파크"


def _mock_build_real_routes(monkeypatch):
    monkeypatch.setattr(
        route_planner,
        "_build_real_routes",
        lambda selected_places, transport_mode: (
            [
                {
                    "from": selected_places[i]["name"], "to": selected_places[i + 1]["name"],
                    "estimated_time": "약 7분", "estimated_time_minutes": 7,
                }
                for i in range(len(selected_places) - 1)
            ],
            [],
        ),
    )


def _fake_backfill_place():
    return {
        "name": "장소C", "title": "장소C", "content_id": "3", "address": "",
        "longitude": 128.93, "latitude": 37.73, "image_url": "",
        "reason": "", "source": "rag", "category": "관광지", "content_type_id": None,
        "rating": None, "review_count": None,
    }


def test_build_place_move_route_plan_moves_place_and_backfills_source(monkeypatch):
    _mock_build_real_routes(monkeypatch)
    monkeypatch.setattr(
        route_planner, "_search_rag_places", lambda **kwargs: [_fake_backfill_place()]
    )
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)

    result = build_place_move_route_plan(
        parsed={"city": "강릉"},
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        source_day=2,
        source_time_slot="오전",
        destination_day=1,
        destination_time_slot="오전",
    )

    daily_schedule = result["daily_schedule"]
    # destination(Day 1 오전)에는 옮겨온 장소B가 들어가고, 원래 있던 장소A는 제외된다
    assert daily_schedule[0]["day"] == "Day 1"
    assert daily_schedule[0]["time_slot"] == "오전"
    assert daily_schedule[0]["place_name"] == "장소B"
    # source(Day 2 오전)의 빈 자리는 새로 검색된 장소로 채워진다
    assert daily_schedule[2]["day"] == "Day 2"
    assert daily_schedule[2]["place_name"] == "장소C"
    # 체크인(숙박) 슬롯은 이동 대상이 아니므로 그대로 유지
    assert daily_schedule[1]["place_name"] == "강릉호텔"

    selected_names = {p["name"] for p in result["selected_places"]}
    assert selected_names == {"장소B", "강릉호텔", "장소C"}
    assert "장소A" not in selected_names

    assert any("옮겼습니다" in w for w in result["warnings"])


def test_build_place_move_route_plan_defaults_to_first_movable_slot(monkeypatch):
    _mock_build_real_routes(monkeypatch)
    monkeypatch.setattr(
        route_planner, "_search_rag_places", lambda **kwargs: [_fake_backfill_place()]
    )
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)

    # 시간대를 지정 안 해도(None) 그 날짜의 첫 이동 가능한 슬롯을 자동으로 골라야 한다
    result = build_place_move_route_plan(
        parsed={"city": "강릉"},
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        source_day=2,
        source_time_slot=None,
        destination_day=1,
        destination_time_slot=None,
    )

    daily_schedule = result["daily_schedule"]
    assert daily_schedule[0]["place_name"] == "장소B"
    assert daily_schedule[2]["place_name"] == "장소C"


def test_build_place_move_route_plan_returns_unchanged_when_slot_missing():
    result = build_place_move_route_plan(
        parsed={"city": "강릉"},
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        source_day=1,
        source_time_slot="저녁",  # Day 1에는 저녁 슬롯이 없음
        destination_day=2,
        destination_time_slot="오전",
    )

    assert result["daily_schedule"] == _fake_previous_result()["daily_schedule"]


def test_build_place_move_route_plan_cancels_when_backfill_not_found(monkeypatch):
    # source 자리를 채울 후보를 못 찾으면 이동 자체를 취소하고 기존 일정을 그대로 유지해야 한다
    # (destination만 바뀌고 source가 빈 채로 남는 반쪽짜리 상태를 피하기 위함).
    monkeypatch.setattr(route_planner, "_search_rag_places", lambda **kwargs: [])
    monkeypatch.setattr(route_planner, "_search_real_places", lambda **kwargs: [])

    result = build_place_move_route_plan(
        parsed={"city": "강릉"},
        transport_mode="대중교통",
        people_count=2,
        previous_result=_fake_previous_result(),
        source_day=2,
        source_time_slot="오전",
        destination_day=1,
        destination_time_slot="오전",
    )

    assert result["daily_schedule"] == _fake_previous_result()["daily_schedule"]
    assert any("찾지 못해" in w for w in result["warnings"])


def test_build_time_slots_day_intensity_overrides_only_affects_that_day():
    slots = route_planner._build_time_slots(
        travel_days=3,
        schedule_intensity="보통",
        season="여름",
        day_intensity_overrides={2: "빡빡한 일정"},
    )
    day1 = [s for s in slots if s[0] == "Day 1"]
    day2 = [s for s in slots if s[0] == "Day 2"]
    day3 = [s for s in slots if s[0] == "Day 3"]

    # 오버라이드가 적용된 Day 2만 관광지 슬롯이 하나 더(늦은 오후) 붙어야 한다
    assert ("Day 2", "늦은 오후") in day2
    assert ("Day 1", "늦은 오후") not in day1
    assert ("Day 3", "늦은 오후") not in day3


def test_search_day_partitioned_candidates_uses_override_style_per_day(monkeypatch):
    def fake_search_rag_places(city, travel_style, prefer_local, max_places):
        if "액티비티" in travel_style:
            return [
                {
                    "name": "서핑레슨", "title": "서핑레슨", "content_id": "10", "address": "",
                    "longitude": 128.90, "latitude": 37.70, "category": "레포츠", "source": "rag",
                },
            ]
        return [
            {
                "name": "안목해변", "title": "안목해변", "content_id": "1", "address": "",
                "longitude": 128.90, "latitude": 37.70, "category": "관광지", "source": "rag",
            },
            {
                "name": "테라로사", "title": "테라로사", "content_id": "2", "address": "",
                "longitude": 128.91, "latitude": 37.71, "category": "관광지", "source": "rag",
            },
        ]

    monkeypatch.setattr(route_planner, "_search_rag_places", fake_search_rag_places)
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)

    time_slots = [("Day 1", "오전"), ("Day 1", "오후"), ("Day 2", "오전")]

    candidates, data_source, _ = route_planner._search_day_partitioned_candidates(
        city="강릉",
        time_slots=time_slots,
        travel_style=["바다"],
        prefer_local=False,
        day_travel_style_overrides={2: ["액티비티"]},
    )

    names = [c["name"] for c in candidates]
    # Day 1(전체 공통 취향)이 먼저, Day 2(오버라이드된 취향)가 그 다음 순서로 이어붙어야 한다
    assert names == ["안목해변", "테라로사", "서핑레슨"]
    assert data_source == "rag"


def test_search_day_partitioned_candidates_pads_shortfall_with_global_fallback(monkeypatch):
    # Day 2 전용 취향("액티비티")으로는 슬롯 수(2개)를 다 못 채우는 상황을 흉내낸다.
    def fake_search_rag_places(city, travel_style, prefer_local, max_places):
        if "액티비티" in travel_style:
            return [
                {
                    "name": "서핑레슨", "title": "서핑레슨", "content_id": "10", "address": "",
                    "longitude": 128.90, "latitude": 37.70, "category": "레포츠", "source": "rag",
                },
            ]
        # 전체 공통 취향("바다") 검색 — Day 1 몫 + 부족분 보충용으로 재사용됨
        return [
            {
                "name": "안목해변", "title": "안목해변", "content_id": "1", "address": "",
                "longitude": 128.90, "latitude": 37.70, "category": "관광지", "source": "rag",
            },
            {
                "name": "테라로사", "title": "테라로사", "content_id": "2", "address": "",
                "longitude": 128.91, "latitude": 37.71, "category": "관광지", "source": "rag",
            },
        ]

    monkeypatch.setattr(route_planner, "_search_rag_places", fake_search_rag_places)
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)

    # Day 1: 1슬롯(전체 공통), Day 2: 2슬롯(오버라이드, 근데 후보가 1개뿐)
    time_slots = [("Day 1", "오전"), ("Day 2", "오전"), ("Day 2", "오후")]

    candidates, _, _ = route_planner._search_day_partitioned_candidates(
        city="강릉",
        time_slots=time_slots,
        travel_style=["바다"],
        prefer_local=False,
        day_travel_style_overrides={2: ["액티비티"]},
    )

    names = [c["name"] for c in candidates]
    # Day 1(안목해변) + Day 2(서핑레슨 하나뿐이라 전체 공통 취향으로 1개 보충 = 테라로사)
    assert names == ["안목해변", "서핑레슨", "테라로사"]


def test_build_route_plan_applies_daily_preferences_per_day(monkeypatch):
    sea_items = [
        {
            "content_id": str(i), "title": f"바다장소{i}", "address": "강원특별자치도 강릉시",
            "category": "관광지", "longitude": 128.90 + i * 0.001, "latitude": 37.70 + i * 0.001,
        }
        for i in range(1, 5)
    ]
    activity_items = [
        {
            "content_id": str(100 + i), "title": f"액티비티장소{i}", "address": "강원특별자치도 강릉시",
            "category": "레포츠", "longitude": 128.90 + i * 0.001, "latitude": 37.70 + i * 0.001,
        }
        for i in range(1, 4)
    ]

    def fake_retrieve(taste_text, match_count, city):
        return activity_items if "액티비티" in taste_text else sea_items

    monkeypatch.setattr(route_planner, "retrieve_places_by_taste", fake_retrieve)
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7", "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시",
        },
    )
    monkeypatch.setattr(route_planner, "get_route", lambda origin, destination: {})
    monkeypatch.setattr(
        route_planner,
        "summarize_route",
        lambda route: {
            "distance_km": 1.0, "duration_min": 10, "taxi_fare": 5000, "toll_fare": 0,
        },
    )
    monkeypatch.setattr(route_planner, "get_course_content_ids", lambda city, **kwargs: [])
    # RAG mock(fake_retrieve)은 음식점/숙박 카테고리를 절대 반환하지 않으므로,
    # _search_restaurant_places/_search_lodging_place의 TourAPI 실시간 폴백이 실제
    # 네트워크를 타지 않도록 빈 결과로 막아둔다(이 테스트의 관심사는 daily_preferences
    # 오버라이드 동작이지 음식점/숙박 폴백이 아님).
    monkeypatch.setattr(route_planner, "search_keyword", lambda **kwargs: [])

    result = route_planner.build_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "여유로운 일정",
            "daily_preferences": [
                {"day": 2, "travel_style": ["액티비티"], "schedule_intensity": None},
            ],
        },
        transport_mode="대중교통",
        people_count=2,
    )

    day1_places = {e["place_name"] for e in result["daily_schedule"] if e["day"] == "Day 1"}
    day2_places = {e["place_name"] for e in result["daily_schedule"] if e["day"] == "Day 2"}

    # Day 2만 오버라이드된 "액티비티" 취향 장소가 들어가고, Day 1은 전체 공통 "바다" 취향을 따른다
    assert any(name.startswith("액티비티장소") for name in day2_places)
    assert not any(name.startswith("액티비티장소") for name in day1_places)
    assert any(name.startswith("바다장소") for name in day1_places)


def test_search_day_partitioned_candidates_places_must_include_on_specified_day(monkeypatch):
    # 취향 검색 결과는 매 호출마다 서로 다른(전역 유일한) 후보를 주도록 카운터를 쓴다 —
    # 이름이 겹치면 _exclude_existing이 걸러내서 폴백 로직까지 타게 되어 이 테스트의
    # 관심사(필수 장소가 지정한 날짜의 슬롯 맨 앞에 오는지)와 무관한 경로가 섞이게 된다.
    counter = iter(range(1, 100))

    def fake_search_rag_places(city, travel_style, prefer_local, max_places):
        return [
            {
                "name": f"일반후보{next(counter)}", "title": "일반후보", "content_id": str(next(counter)),
                "address": "", "longitude": 128.9, "latitude": 37.7, "category": "관광지",
            }
            for _ in range(max_places)
        ]

    monkeypatch.setattr(route_planner, "_search_rag_places", fake_search_rag_places)
    monkeypatch.setattr(route_planner, "_fill_missing_place_details", lambda places: places)

    must_include_place = {
        "name": "국립경주박물관", "title": "국립경주박물관", "content_id": "999",
        "address": "", "longitude": 128.9, "latitude": 37.7, "category": "관광지",
    }

    time_slots = [("Day 1", "오전"), ("Day 1", "오후"), ("Day 2", "오전"), ("Day 2", "오후")]

    candidates, _, _ = route_planner._search_day_partitioned_candidates(
        city="경주",
        time_slots=time_slots,
        travel_style=["문화"],
        prefer_local=False,
        day_travel_style_overrides={},
        day_must_include_places={2: [must_include_place]},
    )

    names = [c["name"] for c in candidates]
    # Day 1은 2슬롯 모두 일반 취향 검색 결과, Day 2는 필수 장소가 맨 앞 슬롯에 오고
    # 남은 1슬롯만 취향 검색으로 채워져야 한다 (musts가 다음 날짜로 안 밀려나감).
    assert len(names) == 4
    assert names[:2] == ["일반후보1", "일반후보3"]
    assert names[2] == "국립경주박물관"
    assert names[3].startswith("일반후보")


def test_build_route_plan_places_must_include_on_daily_preferences_day(monkeypatch):
    # 실사용에서 실제로 재현된 버그: 식당 후보(restaurant_places)가 하나라도 있으면
    # 기존 candidate_count 절삭 방식이 뒤쪽 날짜(Day 2)의 후보를 통째로 잘라내서
    # must-include 장소가 사라졌다. 그 조건을 그대로 재현하려고 RAG는 "관광지"만 주고
    # (기존처럼) search_keyword가 음식점 contentTypeId 조회에는 실제로 결과를 주도록 한다.
    def fake_retrieve(taste_text, match_count, city):
        return [
            {
                "content_id": str(i), "title": f"일반장소{i}", "address": "강원특별자치도 강릉시",
                "category": "관광지", "longitude": 128.90 + i * 0.001, "latitude": 37.70 + i * 0.001,
            }
            for i in range(1, 6)
        ]

    def fake_search_keyword(keyword=None, content_type_id=None, num_of_rows=20, page_no=1):
        # _resolve_must_include_place가 "강릉 오죽헌테스트전용" 같은 조합으로 조회할 때만
        # 결과를 준다.
        if keyword and "오죽헌테스트전용" in keyword:
            return [
                {
                    "contentid": "888", "title": "오죽헌테스트전용", "addr1": "강원특별자치도 강릉시",
                    "mapx": "128.9", "mapy": "37.7", "contenttypeid": "12",
                }
            ]
        # _search_restaurant_places의 TourAPI 실시간 폴백 — 실사용에서 늘 채워지는
        # 식당 후보를 흉내낸다.
        if content_type_id == route_planner.RESTAURANT_CONTENT_TYPE_ID:
            return [
                {
                    "contentid": f"7{i}", "title": f"식당{i}", "addr1": "강원특별자치도 강릉시",
                    "mapx": "128.9", "mapy": "37.7", "contenttypeid": "39",
                }
                for i in range(1, 4)
            ]
        return []

    monkeypatch.setattr(route_planner, "retrieve_places_by_taste", fake_retrieve)
    monkeypatch.setattr(route_planner, "search_keyword", fake_search_keyword)
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7", "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시",
        },
    )
    monkeypatch.setattr(route_planner, "get_route", lambda origin, destination: {})
    monkeypatch.setattr(
        route_planner,
        "summarize_route",
        lambda route: {
            "distance_km": 1.0, "duration_min": 10, "taxi_fare": 5000, "toll_fare": 0,
        },
    )
    monkeypatch.setattr(route_planner, "get_course_content_ids", lambda city, **kwargs: [])

    result = route_planner.build_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["바다"],
            "prefer_local": False,
            "schedule_intensity": "여유로운 일정",
            "daily_preferences": [
                {"day": 2, "must_include_places": ["오죽헌테스트전용"]},
            ],
        },
        transport_mode="대중교통",
        people_count=2,
    )

    day1_places = {e["place_name"] for e in result["daily_schedule"] if e["day"] == "Day 1"}
    day2_places = {e["place_name"] for e in result["daily_schedule"] if e["day"] == "Day 2"}

    # "2일차에는 오죽헌테스트전용 가고 싶어"(처음 계획 요청)가 실제로 Day 2에 배치되고,
    # Day 1에는 섞여 들어가지 않아야 한다.
    assert "오죽헌테스트전용" in day2_places
    assert "오죽헌테스트전용" not in day1_places


def test_build_route_plan_does_not_force_off_theme_related_place_when_no_room(monkeypatch):
    # related_places(같은 TourAPI 여행코스에 묶여 있다는 이유만으로 뽑힌 연관 관광지)는
    # travel_style 적합성을 전혀 안 본다. 취향 검색만으로 필요한 슬롯을 이미 다 채울 수
    # 있는데도 related_places를 위해 억지로 자리를 마련하면, 요청한 테마와 무관한 장소가
    # "그냥 무작정" 일정에 끼어드는 문제가 생긴다. 자리가 남을 때만 채워져야 한다.
    def fake_retrieve(taste_text, match_count, city):
        return [
            {
                "content_id": str(i), "title": f"관광지{i}", "address": "강원특별자치도 강릉시",
                "category": "관광지", "longitude": 128.90 + i * 0.001, "latitude": 37.70 + i * 0.001,
            }
            for i in range(1, 6)
        ]

    def fake_search_keyword(keyword=None, content_type_id=None, num_of_rows=20, page_no=1):
        if content_type_id == route_planner.RESTAURANT_CONTENT_TYPE_ID:
            return [
                {
                    "contentid": f"7{i}", "title": f"식당{i}", "addr1": "강원특별자치도 강릉시",
                    "mapx": "128.9", "mapy": "37.7", "contenttypeid": "39",
                }
                for i in range(1, 4)
            ]
        return []

    monkeypatch.setattr(route_planner, "retrieve_places_by_taste", fake_retrieve)
    monkeypatch.setattr(route_planner, "search_keyword", fake_search_keyword)
    monkeypatch.setattr(
        route_planner,
        "get_detail_common",
        lambda content_id: {
            "mapx": "128.9", "mapy": "37.7", "lDongRegnCd": "51", "lDongSignguCd": "150",
            "addr1": "강원특별자치도 강릉시", "contenttypeid": "12",
        },
    )
    monkeypatch.setattr(route_planner, "get_route", lambda origin, destination: {})
    monkeypatch.setattr(
        route_planner,
        "summarize_route",
        lambda route: {
            "distance_km": 1.0, "duration_min": 10, "taxi_fare": 5000, "toll_fare": 0,
        },
    )
    # "관광지1"이 코스 courseA에 포함돼 있고, 같은 코스에 "오프테마장소"도 있다고 흉내낸다.
    monkeypatch.setattr(route_planner, "get_course_content_ids", lambda city, **kwargs: ["courseA"])
    monkeypatch.setattr(
        route_planner, "cached_call", lambda namespace, params, fetch_fn, ttl_seconds=None: fetch_fn()
    )
    monkeypatch.setattr(
        route_planner,
        "get_detail_info",
        lambda content_id, content_type_id: [
            {"subcontentid": "1", "subname": "관광지1"},
            {"subcontentid": "999", "subname": "오프테마장소"},
        ],
    )

    result = route_planner.build_route_plan(
        parsed={
            "city": "강릉",
            "duration": "1박 2일",
            "travel_style": ["역사답사"],
            "prefer_local": False,
            "schedule_intensity": "보통",
        },
        transport_mode="대중교통",
        people_count=2,
    )

    all_place_names = {e["place_name"] for e in result["daily_schedule"]}
    # 취향 검색(관광지1~5)과 식당(식당1~3)만으로 이미 슬롯이 다 차므로, 테마와 무관하게
    # 코스로만 엮인 "오프테마장소"는 일정에 들어가면 안 된다.
    assert "오프테마장소" not in all_place_names
