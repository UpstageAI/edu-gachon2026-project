from datetime import date

from PIL import Image

from app.agents import nodes, report_ingestion
from app.agents.report_catalog import MARKET_REPORT_SLOTS
from app.agents.report_render import build_indicator_views, render_market_report_image


def test_market_report_catalog_has_21_unique_slots():
    positions = [slot.position for slot in MARKET_REPORT_SLOTS]
    aliases = {slot.indicator_id: set(slot.aliases) for slot in MARKET_REPORT_SLOTS}

    assert len(MARKET_REPORT_SLOTS) == 21
    assert positions == list(range(1, 22))
    assert len({slot.indicator_id for slot in MARKET_REPORT_SLOTS}) == 21
    assert "topic_fed_funds" in aliases["us_policy_rate"]
    assert "topic_us_rate" not in aliases["us_policy_rate"]


def test_build_indicator_views_maps_values_and_missing_slots():
    views = build_indicator_views(
        [
            {
                "indicator_id": "kospi",
                "name": "코스피",
                "value": 2650.25,
                "prev": 2600.25,
                "change_pct": 1.92,
                "unit": "pt",
                "source": "fixture",
            }
        ],
        missing_indicators=["kosdaq"],
    )

    assert len(views) == 21
    kospi = views[0]
    assert kospi["display_name"] == "코스피"
    assert kospi["current_value"] == 2650.25
    assert kospi["change_value"] == 50.0
    assert kospi["change_percent"] == 1.92
    assert kospi["direction"] == "up"

    kosdaq = views[1]
    assert kosdaq["display_name"] == "코스닥"
    assert kosdaq["missing"] is True
    assert kosdaq["direction"] == "flat"


def test_build_indicator_views_treats_nan_as_missing_and_formats_units():
    views = build_indicator_views(
        [
            {
                "indicator_id": "shanghai",
                "name": "상해종합",
                "value": float("nan"),
                "prev": 3200.0,
                "unit": "pt",
                "source": "fixture",
            },
            {
                "indicator_id": "btc",
                "name": "비트코인",
                "value": 63138.0,
                "prev": 62087.99,
                "change_pct": 1.69,
                "unit": "USD",
                "source": "fixture",
            },
            {
                "indicator_id": "us_policy_rate",
                "name": "미국 기준금리",
                "value": 3.75,
                "prev": 3.75,
                "unit": "%",
                "source": "fixture",
            },
        ]
    )

    shanghai = next(view for view in views if view["indicator_id"] == "shanghai")
    btc = next(view for view in views if view["indicator_id"] == "btc")
    us_policy_rate = next(view for view in views if view["indicator_id"] == "us_policy_rate")

    assert shanghai["missing"] is True
    assert shanghai["current_value"] is None
    assert shanghai["value_text"] == "N/A"
    assert btc["value_text"] == "63,138.00 USD"
    assert us_policy_rate["value_text"] == "3.75 %"


def test_render_market_report_image_creates_1080_png(tmp_path):
    out_path = tmp_path / "market_report_20260710.png"
    indicators = [
        {
            "indicator_id": "kospi",
            "name": "코스피",
            "value": 2650.25,
            "prev": 2600.25,
            "change_pct": 1.92,
            "unit": "pt",
            "source": "fixture",
        },
        {
            "indicator_id": "btc",
            "name": "비트코인",
            "value": 63138.0,
            "prev": 62087.99,
            "change_pct": 1.69,
            "unit": "USD",
            "source": "fixture",
        },
    ]

    result = render_market_report_image(
        indicators,
        run_date=date(2026, 7, 10),
        out_path=out_path,
        missing_indicators=["silver"],
    )

    assert result == str(out_path)
    with Image.open(out_path) as image:
        assert image.format == "PNG"
        assert image.size == (1080, 1080)
        assert image.mode == "RGB"


def test_build_report_image_keeps_live_report_indicators_for_explanation(monkeypatch, tmp_path):
    monkeypatch.setenv("FINBRIEF_REPORT_OUT", str(tmp_path))
    monkeypatch.setattr(
        report_ingestion,
        "collect_report_indicators",
        lambda run_date: (
            [
                {
                    "indicator_id": "btc",
                    "name": "비트코인",
                    "value": 65000.0,
                    "prev": 63000.0,
                    "change_pct": 3.17,
                    "unit": "USD",
                    "source": "fixture",
                }
            ],
            ["shanghai"],
        ),
    )

    out = nodes.build_report_image({"live_data": True, "run_date": "2026-07-14"})

    assert out["report_indicators"][0]["indicator_id"] == "btc"
    assert out["report_missing_indicators"] == ["shanghai"]
    assert out["report_url"]
