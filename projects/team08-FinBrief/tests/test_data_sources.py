from datetime import date

from app.tools.data_sources.ecos import parse_ecos_key_statistics
from app.tools.data_sources.fred import parse_fred_observations
from app.tools.data_sources.yfinance_source import parse_yfinance_price_rows


def test_parse_fred_observations_skips_missing_values_and_calculates_change():
    payload = {
        "observations": [
            {"date": "2026-07-07", "value": "4.11"},
            {"date": "2026-07-08", "value": "."},
            {"date": "2026-07-09", "value": "4.21"},
        ]
    }

    values = parse_fred_observations(
        payload,
        indicator_id="topic_us_rate:DGS10",
        name="미국 10년물 금리",
        unit="%",
    )

    assert len(values) == 2
    assert values[-1].source == "fred"
    assert values[-1].value_date == date(2026, 7, 9)
    assert values[-1].current_value == 4.21
    assert values[-1].previous_value == 4.11
    assert round(values[-1].change_value or 0, 2) == 0.10


def test_parse_yfinance_price_rows_uses_close_values():
    rows = [
        {"date": "2026-07-08", "Close": 15980.0},
        {"date": "2026-07-09", "Close": 16020.0},
    ]

    values = parse_yfinance_price_rows(
        rows,
        indicator_id="topic_nasdaq:^IXIC",
        name="나스닥",
        unit="pt",
    )

    assert [item.source for item in values] == ["yfinance", "yfinance"]
    assert values[-1].current_value == 16020.0
    assert values[-1].previous_value == 15980.0
    assert round(values[-1].change_percent or 0, 3) == 0.25


def test_parse_yfinance_price_rows_skips_non_finite_values():
    rows = [
        {"date": "2026-07-08", "Close": float("nan")},
        {"date": "2026-07-09", "Close": 3990.24},
    ]

    values = parse_yfinance_price_rows(
        rows,
        indicator_id="shanghai",
        name="상해종합",
        unit="pt",
    )

    assert len(values) == 1
    assert values[0].current_value == 3990.24
    assert values[0].previous_value is None


def test_parse_ecos_key_statistics_maps_latest_value():
    payload = {
        "KeyStatisticList": {
            "row": [
                {
                    "CLASS_NAME": "환율",
                    "KEYSTAT_NAME": "원/달러 환율(종가)",
                    "DATA_VALUE": "1532",
                    "CYCLE": "20260626",
                    "UNIT_NAME": "원",
                }
            ]
        }
    }

    values = parse_ecos_key_statistics(payload, indicator_id_prefix="ecos")

    assert len(values) == 1
    assert values[0].indicator_id == "ecos:원/달러 환율(종가)"
    assert values[0].source == "ecos"
    assert values[0].value_date == date(2026, 6, 26)
    assert values[0].current_value == 1532.0
