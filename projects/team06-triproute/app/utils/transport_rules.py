import math


def estimate_public_transport_time(car_minutes: int) -> int:
    """
    자동차 기준 소요시간을 바탕으로 대중교통 예상 소요시간을 추정합니다.
    MVP에서는 실시간 환승 API를 사용하지 않으므로 참고용 값입니다.
    """

    return math.ceil(car_minutes * 1.7)


def estimate_public_transport_fee(distance_km: float, people_count: int = 1) -> int:
    """
    거리 기반 대중교통 요금을 추정합니다.
    기본요금 1,550원, 10km 초과 시 5km 단위로 100원씩 가산하는 단순 MVP 규칙입니다.
    """

    base_fee = 1550

    if distance_km <= 10:
        fee_per_person = base_fee
    else:
        extra_distance = distance_km - 10
        extra_units = math.ceil(extra_distance / 5)
        fee_per_person = base_fee + extra_units * 100

    return fee_per_person * people_count


def recommend_vehicle_by_people(people_count: int) -> dict:
    """
    인원수에 따라 렌터카 차종과 1일 렌트비를 추천합니다.
    MVP용 평균 추정값입니다.
    """

    if people_count <= 2:
        return {
            "vehicle_type": "소형차",
            "daily_rental_fee": 60000,
            "reason": "1~2명 여행에 적합한 경제적인 차량입니다.",
        }

    if people_count <= 4:
        return {
            "vehicle_type": "중형차",
            "daily_rental_fee": 80000,
            "reason": "3~4명 여행에 적합한 일반적인 차량입니다.",
        }

    if people_count <= 6:
        return {
            "vehicle_type": "SUV/대형차",
            "daily_rental_fee": 120000,
            "reason": "5~6명 여행과 짐이 많은 일정에 적합합니다.",
        }

    return {
        "vehicle_type": "승합차",
        "daily_rental_fee": 150000,
        "reason": "7명 이상 단체 여행에 적합합니다.",
    }


def estimate_rental_car_cost(people_count: int, travel_days: int) -> dict:
    """
    인원수와 여행일수를 바탕으로 렌터카 비용을 계산합니다.
    """

    vehicle = recommend_vehicle_by_people(people_count)
    rental_cost = vehicle["daily_rental_fee"] * travel_days

    return {
        "vehicle_type": vehicle["vehicle_type"],
        "daily_rental_fee": vehicle["daily_rental_fee"],
        "travel_days": travel_days,
        "rental_cost": rental_cost,
        "reason": vehicle["reason"],
    }


TAXI_SEATS_PER_CAB = 4


def estimate_transport_cost(
    transport_mode: str,
    distance_km: float,
    car_minutes: int,
    taxi_fare: int | None,
    people_count: int,
    travel_days: int = 1,
) -> dict:
    """
    이동수단별 교통비와 예상 시간을 계산합니다.
    """

    if transport_mode == "택시":
        # 경로 조회 실패 시 taxi_fare가 0으로 채워지므로(route_planner._unavailable_route),
        # 0 이하는 실제 무료 요금이 아니라 데이터 누락으로 간주한다
        # (cost_rules.to_positive_int와 동일한 규칙).
        if taxi_fare is None or taxi_fare <= 0:
            return {
                "transport_mode": transport_mode,
                "estimated_time_minutes": car_minutes,
                "estimated_cost": 0,
                "is_estimated": True,
            }

        cabs_needed = math.ceil(people_count / TAXI_SEATS_PER_CAB)
        return {
            "transport_mode": transport_mode,
            "estimated_time_minutes": car_minutes,
            "estimated_cost": taxi_fare * cabs_needed,
            "is_estimated": False,
        }

    if transport_mode == "대중교통":
        return {
            "transport_mode": transport_mode,
            "estimated_time_minutes": estimate_public_transport_time(car_minutes),
            "estimated_cost": estimate_public_transport_fee(distance_km, people_count),
            "is_estimated": True,
        }

    if transport_mode == "자차":
        return {
            "transport_mode": transport_mode,
            "estimated_time_minutes": car_minutes,
            "estimated_cost": 0,
            "is_estimated": True,
            "memo": "자차 비용은 MVP 기준에서 별도 계산하지 않습니다.",
        }

    if transport_mode == "렌터카":
        rental_info = estimate_rental_car_cost(
            people_count=people_count,
            travel_days=travel_days,
        )

        return {
            "transport_mode": transport_mode,
            "estimated_time_minutes": car_minutes,
            "estimated_cost": rental_info["rental_cost"],
            "is_estimated": True,
            "vehicle_recommendation": {
                "vehicle_type": rental_info["vehicle_type"],
                "daily_rental_fee": rental_info["daily_rental_fee"],
                "travel_days": rental_info["travel_days"],
                "reason": rental_info["reason"],
            },
        }

    return {
        "transport_mode": transport_mode,
        "estimated_time_minutes": car_minutes,
        "estimated_cost": 0,
        "is_estimated": True,
    }