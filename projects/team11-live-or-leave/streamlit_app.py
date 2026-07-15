"""
Streamlit UI — 서울 지도를 항상 보여주고, 오른쪽 입력창에 선호(필수 사항)와
구조화된 하드필터(구·기준 장소)를 입력한 뒤 "동네 추천하기" 버튼을 눌러야
추천이 실행된다.

흐름: 우측 입력(필수 사항 자유 텍스트 + 구/기준 장소 구조화 입력) → [버튼 클릭]
      → RecommendationAgent.run(top_n=전체, required_filters=구조화 입력에서
        직접 만든 FilterClause 목록) → 상위 top_n1(진한초록)/다음 top_n2(연한초록)/
        하위 절반(저점수 빨강)+절반(필수조건 미충족 보라) 티어링 → 좌측에 지도,
        동에 마우스오버하면 실제 수치를 툴팁으로. 서울 밖은 베이스맵 자체를
        꺼서 아예 안 그린다.

구·기준 장소는 LLM이 자연어에서 추론하지 않는다 — 멀티셀렉트/텍스트 검색으로
사용자가 직접 고른 값을 코드가 그대로 FilterClause로 옮긴다. "필수 사항" 자유
텍스트(예전 이름 "선택 요구사항")는 가중치·extra_categories 파싱에만 쓰인다.
그래서 "자유 텍스트의 일부가 하드필터로 오인식되는" 버그가 구조적으로 없다.

기준 장소는 입력하는 즉시(텍스트 확정 시) Kakao 검색 후보 최대 5개를 보여주고,
사용자가 그중 하나를 고르면 그 좌표가 지도에 미리보기 핀으로 바로 반영된다
("삼성" 같은 흔한 이름이 엉뚱한 곳으로 뽑히는 걸 막기 위함 — top-1을 그냥
믿지 않고 눈으로 확인 후 선택).

버튼을 누르기 전까지는 텍스트를 아무리 고쳐도 LLM 호출이 일어나지 않는다.
마지막으로 계산된 결과는 st.session_state에 저장해두고, 버튼 클릭이 아닌
다른 위젯(지도 스타일 등) 조작으로 인한 rerun에서도 그 결과를 계속 보여준다.

티어링·hover 텍스트 조립은 결정론적 포맷팅일 뿐이라 LLM을 안 쓴다 — LLM은
result.message(상위 3개 자연어 설명) 하나에만 관여한다 (agent.run 참고).

기본값은 실제 Solar API다 (재입력할 때마다 parse_intent+explain 2회 호출).
UPSTAGE_API_KEY가 없으면 자동으로 mock으로 낮춘다(load_agent 참고, app.agent.factory
공유). 키가 있어도 레이아웃·색깔 확인처럼 빠른 반복 작업만 할 땐 강제로 mock으로 전환 가능:
    USE_MOCK_LLM=1 streamlit run streamlit_app.py
어느 쪽이든 mock으로 동작 중이면 화면에 경고 캡션이 뜬다. main.py(FastAPI)도 이
판단(app.agent.factory.using_mock_llm)을 그대로 공유한다 — 두 앱이 같은
환경변수에 항상 같은 결정을 내린다.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.agent.factory import build_recommendation_agent, mock_llm_reason, using_mock_llm
from app.agent.loop import RecommendationAgent
from app.agent.tools import SEOUL_GU
from app.data.kakao_facility_repository import get_hybrid_facility_repository
from app.schemas.tools import FilterClause

st.set_page_config(page_title="살래말래 — 행정동 추천", layout="wide")

# 티어 컷오프는 고정 개수·고정 비율이 아니라 z-score(평균에서 몇 표준편차
# 떨어져 있는지)로 정한다. Jenks natural breaks도 시도해봤지만 k개 그룹으로
# "무조건" 강제 분할하는 방식이라 강도 조절이 안 됐다(실제 서울 동 점수
# 분포가 뚜렷한 소수 엘리트 구조가 아니라 고르게 퍼져있어서, Jenks로도
# 필터 후 결과의 30%+ 가 top1로 찍히는 경우가 실측됨). z-score는 threshold
# 자체를 조절할 수 있어 "상위 X%만 두드러지게 보이기"라는 원래 목적에
# 맞게 강도를 튜닝했다(1.5σ 이상만 top1 — 실측 결과 전체 기준 top1 6%대,
# neutral 66%대로 원래 의도한 분포에 가장 가까웠다).
Z_TOP1 = 1.5     # 평균 + 1.5σ 초과 → top1(진한초록)
Z_TOP2 = 0.75    # 평균 + 0.75σ 초과 → top2(연한초록)
Z_LOW = -1.5     # 평균 - 1.5σ 미만 → low_score(빨강)

TIER_COLORS = {
    "top1": "#1b5e20",
    "top2": "#81c784",
    "low_score": "#ef5350",
    "disqualified": "#7b1fa2",
    "neutral": "#e0e0e0",
}
TIER_LABELS = {
    "top1": "추천 (상위)",
    "top2": "추천",
    "low_score": "비추천 (낮은 점수)",
    "disqualified": "비추천 (필수조건 미충족)",
    "neutral": "그 외",
}

BORDER_WIDTH = 0.6
BORDER_COLOR = "#616161"

# 지도 베이스 스타일 (MapLibre, 토큰 불필요)
MAP_STYLES = {
    "위성사진": "satellite",
    "위성+도로": "satellite-streets",
    "일반": "open-street-map",
    "어두움": "carto-darkmatter",
}
SEOUL_CENTER = {"lat": 37.5642, "lon": 126.9976}
SEOUL_ZOOM = 10.4
DEFAULT_MAP_STYLE = "어두움"
TIER_OPACITY = 0.62          # 색깔 티어(추천/비추천) — 위성사진이 비쳐 보이도록 반투명
NEUTRAL_TIER_OPACITY = 0.0   # '그 외'는 채우지 않는다 — 서울 안쪽은 위성사진 그대로
OUTSIDE_DIM_OPACITY = 0.6    # 서울 바깥을 어둡게 깔아 서울이 도드라지게(스포트라이트 효과)

# 서울 핵심시설 — 지도 방향감·검증용 고정 마커 (교통/병원/대학/랜드마크)
CORE_FACILITIES: list[dict] = [
    {"name": "서울역", "cat": "교통", "lat": 37.5547, "lon": 126.9707},
    {"name": "용산역", "cat": "교통", "lat": 37.5299, "lon": 126.9646},
    {"name": "청량리역", "cat": "교통", "lat": 37.5802, "lon": 127.0479},
    {"name": "왕십리역", "cat": "교통", "lat": 37.5613, "lon": 127.0374},
    {"name": "강남역", "cat": "교통", "lat": 37.4979, "lon": 127.0276},
    {"name": "홍대입구역", "cat": "교통", "lat": 37.5570, "lon": 126.9236},
    {"name": "김포공항", "cat": "교통", "lat": 37.5586, "lon": 126.7906},
    {"name": "서울대병원", "cat": "병원", "lat": 37.5799, "lon": 126.9990},
    {"name": "세브란스병원", "cat": "병원", "lat": 37.5622, "lon": 126.9410},
    {"name": "삼성서울병원", "cat": "병원", "lat": 37.4881, "lon": 127.0855},
    {"name": "서울아산병원", "cat": "병원", "lat": 37.5270, "lon": 127.1085},
    {"name": "서울대학교", "cat": "대학", "lat": 37.4598, "lon": 126.9511},
    {"name": "연세대학교", "cat": "대학", "lat": 37.5658, "lon": 126.9386},
    {"name": "고려대학교", "cat": "대학", "lat": 37.5895, "lon": 127.0323},
    {"name": "시청", "cat": "랜드마크", "lat": 37.5663, "lon": 126.9779},
    {"name": "경복궁", "cat": "랜드마크", "lat": 37.5796, "lon": 126.9770},
    {"name": "N서울타워", "cat": "랜드마크", "lat": 37.5512, "lon": 126.9882},
    {"name": "코엑스", "cat": "랜드마크", "lat": 37.5088, "lon": 127.0627},
    {"name": "롯데월드타워", "cat": "랜드마크", "lat": 37.5125, "lon": 127.1025},
    {"name": "국회의사당", "cat": "랜드마크", "lat": 37.5319, "lon": 126.9140},
    {"name": "상암 DMC", "cat": "랜드마크", "lat": 37.5779, "lon": 126.8897},
]

@st.cache_resource
def load_agent() -> RecommendationAgent:
    """mock 판단·생성 로직은 app.agent.factory 공유 — main.py(FastAPI)와
    이 판단이 어긋나지 않는다. 여기서는 Streamlit 프로세스 재사용을 위해
    build_recommendation_agent() 결과를 @st.cache_resource로 캐싱만 한다."""
    return build_recommendation_agent()


def _mock_llm_reason() -> str:
    return mock_llm_reason()


# 추천 파이프라인(파싱·필터·스코어링) 코드가 바뀔 때마다 올린다.
# st.cache_data는 함수 인자만 캐시 키로 쓰고 하위 모듈(tools/scoring/solar_llm)
# 코드 변경은 감지하지 못하므로, 버전을 인자로 넘겨 낡은 결과를 무효화한다.
PIPELINE_VERSION = 4  # v4: category/대형병원 필터 제거, 구·기준장소 구조화 입력으로 전환


@st.cache_data(max_entries=128, show_spinner="추천 계산 중…")
def run_agent_cached(
    combined: str, mock: bool, pipeline_version: int, required_filters_json: str
) -> dict:
    """같은 입력(선호 텍스트+구조화 필터)으로는 LLM을 다시 호출하지 않는다.

    Streamlit은 위젯 하나만 바뀌어도 스크립트 전체를 재실행하므로, 캐시가
    없으면 무관한 rerun(예: 지도 스타일 변경)마다 동일 입력으로 parse_intent+
    explain 2회씩 재호출된다. mock 여부를 키에 포함해 mock으로 받은 결과가
    실 LLM 모드에서 재사용되는 일을 막는다.

    required_filters는 FilterClause 리스트 그대로 받지 않고 JSON 문자열로
    받는다 — st.cache_data는 인자를 해시해 캐시 키를 만드는데, pydantic
    모델 리스트보다 문자열이 항상 안전하게 해시된다.

    반환은 AgentResult가 아니라 dict — st.cache_data는 반환값을 pickle하는데,
    Streamlit의 모듈 핫리로드 아래에서는 커스텀 클래스 직렬화가 깨진다
    (UnserializableReturnValueError). 평범한 dict/list/str만 남긴다."""
    required_filters = [FilterClause(**c) for c in json.loads(required_filters_json)]
    return asdict(load_agent().run(combined, top_n=500, required_filters=required_filters))


@st.cache_data
def load_boundaries() -> dict:
    with open("dong_boundaries.geojson", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def dong_centroids(geojson: dict) -> dict[str, tuple[float, float]]:
    """행정동 코드 → 중심점(lon, lat). 상위 3개 추천지를 지도에 점으로
    찍을 때 좌표가 필요한데, recommendations 안엔 코드만 있고 좌표가 없어
    geojson 폴리곤에서 직접 계산한다(Kakao API 불필요 — 로컬 계산)."""
    from shapely.geometry import shape

    return {
        f["properties"]["code"]: (shape(f["geometry"]).centroid.x, shape(f["geometry"]).centroid.y)
        for f in geojson["features"]
    }


@st.cache_data
def load_outside_seoul_mask() -> dict:
    """서울 바깥 전체(지도가 확대/축소돼도 안 뚫리도록 지구 전체 범위)를 덮는
    마스크 폴리곤 — 구멍이 정확히 서울 426개 동의 합집합 모양이다. 위성사진
    위에 이걸 어둡게 깔면 구멍(서울)만 밝게 도드라져 보인다(스포트라이트 효과)."""
    from shapely.geometry import box, mapping, shape
    from shapely.ops import unary_union

    geojson = load_boundaries()
    seoul = unary_union([shape(f["geometry"]) for f in geojson["features"]])
    world = box(-180, -85, 180, 85)  # 위경도 전체(위도는 웹메르카토르 한계인 ±85)
    mask = world.difference(seoul)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "OUTSIDE"}, "geometry": mapping(mask)}
    ]}


def _hover_for_recommendation(rec: dict) -> str:
    raw = rec["scores"]["raw"]
    lines = [
        f"<b>{rec['gu']} {rec['dong']}</b> (종합 {rec['total_score']})",
        f"안전: 범죄율 {raw['crime_rate']}/만명, CCTV {raw['cctv_cnt']}대",
        f"편의: 편의점 {raw['conv_cnt']}·마트 {raw['mart_cnt']}·병원 {raw['hosp_cnt']}",
        f"이동: 버스 {raw['bus_cnt']}개, 지하철 접근성 {raw['subway_access']}",
        f"환경: 공원 {raw['park_cnt']}곳",
    ]
    extra = rec.get("extra_facilities")
    if extra:
        lines.append("요청 업종: " + ", ".join(f"{k} {v}곳" for k, v in extra.items()))
    return "<br>".join(lines)


def _hover_for_disqualified(d: dict) -> str:
    return (f"<b>{d['gu']} {d['dong']}</b><br>"
            f"필수 요구사항 미충족: {', '.join(d['missing'])}")


def _zscore_tier_labels(scores: list[float]) -> list[str]:
    """점수 리스트(순서 유지) → 각 항목의 티어 이름. 평균·표준편차 대비
    z-score로 분류한다 — 표준편차가 0(전부 동점)이거나 n<2면 구분 불가하니
    전부 neutral 처리."""
    n = len(scores)
    if n < 2:
        return ["neutral"] * n
    mean = statistics.mean(scores)
    std = statistics.pstdev(scores)
    if std == 0:
        return ["neutral"] * n

    tiers = []
    for s in scores:
        z = (s - mean) / std
        if z > Z_TOP1:
            tiers.append("top1")
        elif z > Z_TOP2:
            tiers.append("top2")
        elif z < Z_LOW:
            tiers.append("low_score")
        else:
            tiers.append("neutral")
    return tiers


def assign_tiers(recommendations: list[dict], disqualified: list[dict]) -> pd.DataFrame:
    tiers = _zscore_tier_labels([rec["total_score"] for rec in recommendations])
    rows = [
        {
            "code": rec["scores"]["code"], "gu": rec["gu"], "dong": rec["dong"],
            "tier": tier, "hover": _hover_for_recommendation(rec),
        }
        for rec, tier in zip(recommendations, tiers)
    ]

    # 실격 동은 전부 그린다 — 일부만 그리면 나머지가 지도에서 통째로 사라져
    # 구멍이 뚫린다. 필수 필터 결과 수백 개가 실격될 수 있는데(예: 클라이밍장
    # 없는 동 333개), 그 자체가 사용자에게 의미 있는 정보다.
    for d in disqualified:
        rows.append({
            "code": d["code"], "gu": d["gu"], "dong": d["dong"],
            "tier": "disqualified", "hover": _hover_for_disqualified(d),
        })
    return pd.DataFrame(rows)


def neutral_dataframe(geojson: dict) -> pd.DataFrame:
    """아직 아무 조건도 입력하지 않았을 때 — 전체 동을 회색으로만 표시."""
    rows = []
    for feat in geojson["features"]:
        p = feat["properties"]
        rows.append({
            "code": p["code"], "gu": p["gu"], "dong": p["dong"],
            "tier": "neutral", "hover": f"<b>{p['gu']} {p['dong']}</b>",
        })
    return pd.DataFrame(rows)


# scattermap의 marker.symbol(예: "triangle")은 MapLibre Maki 아이콘셋의 고정
# 스프라이트라 marker.color를 반영하지 못한다(검정으로만 나옴). 유니코드
# 삼각형 글리프를 text로 찍는 우회책도 시도했으나 그 글리프가 지도 폰트셋에
# 없어 마찬가지로 색 없이 깨진 채 렌더링됐다 — 그래서 색이 확실히 먹는
# 원형 마커(핵심시설과 동일 방식)로 통일했다(render_map 참고).
POINT_STYLE = {
    # 확정된 근처 필터 기준점(추천 실행 후): 크고 눈에 띄는 노란 원
    "landmark": dict(color="#ffd600"),
    # 기준 장소 후보를 고르는 중(추천 실행 전) 미리보기: 주황 원 — 아직
    # 적용 안 됐다는 걸 색으로 구분한다. 후보를 바꿔 눌러보면 이 핀이 바로 옮겨간다.
    "preview": dict(color="#ff9100"),
    # 대시보드 설명(explain)이 실제로 언급하는 상위 3개 동 — 지도에서도
    # 바로 찾을 수 있게 보라색 점으로 별도 표시. top1/top2 tier 색(초록)과
    # 겹쳐도 구분되도록 원 마커를 얹는다.
    "top3": dict(color="#aa00ff"),
}
POINT_LABELS = {
    "landmark": "선택한 장소", "preview": "선택한 장소 (미리보기)", "top3": "상위 3개 추천",
}


def render_map(
    df: pd.DataFrame,
    geojson: dict,
    points: list[dict] | None = None,
    map_style: str = "satellite",
    show_core: bool = True,
) -> None:
    """MapLibre 타일 기반 지도(px.choropleth_map) — 위성사진 등 실제 베이스맵
    위에 행정동 티어를 반투명으로 얹는다. 예전 px.choropleth(SVG)에서 쓰던
    CSS :hover 광택 효과는 WebGL 타일 렌더러에는 폴리곤별 DOM이 없어 불가 —
    위성 베이스맵과 맞바꾼 트레이드오프다. plotly 내장 hover 툴팁은 유지된다.
    """
    fig = px.choropleth_map(
        df, geojson=geojson, locations="code", color="tier",
        featureidkey="properties.code",
        color_discrete_map=TIER_COLORS,
        category_orders={"tier": list(TIER_COLORS)},
        custom_data=["hover"],
        map_style=map_style,
        center=SEOUL_CENTER, zoom=SEOUL_ZOOM,
        opacity=TIER_OPACITY,
    )
    fig.update_traces(
        hovertemplate="%{customdata[0]}<extra></extra>",
        marker_line_width=BORDER_WIDTH, marker_line_color=BORDER_COLOR,
    )

    # 서울 바깥을 어둡게 깔아 서울이 도드라지게 (스포트라이트 효과). 구멍이
    # 정확히 서울 모양이라 Seoul 안쪽 fill(위 choropleth_map)과 겹치지 않는다 —
    # 그래서 trace 순서 상관없이 시각적으로 안전하다.
    mask_geojson = load_outside_seoul_mask()
    fig.add_trace(go.Choroplethmap(
        geojson=mask_geojson, locations=["OUTSIDE"], featureidkey="properties.id",
        z=[1], colorscale=[[0, "black"], [1, "black"]], showscale=False,
        marker=dict(opacity=OUTSIDE_DIM_OPACITY, line=dict(width=0)),
        name="서울 바깥", hoverinfo="skip",
    ))

    for trace in fig.data:
        tier_color = TIER_COLORS.get(trace.name, "#333333")
        trace.hoverlabel = dict(
            bgcolor=tier_color, bordercolor="white",
            font=dict(color="white", size=14, family="Arial Black"),
        )
        if trace.name == "neutral":
            trace.marker.opacity = NEUTRAL_TIER_OPACITY
        trace.name = TIER_LABELS.get(trace.name, trace.name)

    # 서울 핵심시설 — 방향감 기준점 (교통/병원/대학/랜드마크, 범례로 켜고 끔)
    if show_core:
        fig.add_scattermap(
            lon=[f["lon"] for f in CORE_FACILITIES], lat=[f["lat"] for f in CORE_FACILITIES],
            mode="markers+text",
            marker=dict(size=10, color="#00e5ff"),
            text=[f["name"] for f in CORE_FACILITIES],
            textfont=dict(size=10, color="#ffffff"),
            textposition="top center",
            name="핵심시설",
            hovertemplate="%{text}<extra></extra>",
            hoverlabel=dict(bgcolor="#263238", font=dict(color="white", size=13)),
        )

    # Kakao 좌표 핀 — 필터가 실제로 어떤 위치를 근거로 걸렸는지 눈으로 검증용.
    # 예전엔 삼각형을 텍스트 글리프(▲)로 그렸는데, 그 유니코드 글리프가
    # 지도 폰트셋(MapLibre 스프라이트)에 없어 색이 안 먹은 채 깨진 검은
    # 삼각형으로 렌더링되는 문제가 있었다. marker.symbol="triangle"도 색이
    # 안 먹는 건 마찬가지라(둘 다 시도해봤음) — 대신 색이 확실히 먹는 원형
    # 마커(핵심시설 마커와 동일 방식)를 크게 키워 눈에 띄게 한다.
    for kind in ("preview", "landmark", "top3"):  # 상위 3개 추천 점이 맨 위에 오도록 마지막에
        pts = [p for p in (points or []) if p["kind"] == kind]
        if pts:
            color = POINT_STYLE[kind]["color"]
            fig.add_scattermap(
                lon=[p["lon"] for p in pts], lat=[p["lat"] for p in pts],
                mode="markers",
                marker=dict(size=14, color=color),
                name=POINT_LABELS[kind],
                hovertext=[p["label"] for p in pts],
                hovertemplate="%{hovertext}<extra></extra>",
                hoverlabel=dict(bgcolor="#263238", font=dict(color="white", size=13)),
            )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), height=760,
        legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    bgcolor="rgba(0,0,0,0.45)", font=dict(color="white")),
        # 위젯 하나 건드릴 때마다(체크박스·셀렉트박스·텍스트 blur) Streamlit이
        # 완전히 새 Figure를 넘기는데, uirevision이 없으면 Plotly가 이걸 "새
        # 지도"로 보고 사용자가 확대/이동해둔 카메라 위치를 매번 초기화한다.
        # 고정값으로 두면 데이터(색·핀)만 갱신되고 카메라는 유지된다.
        uirevision="seoul-map",
    )
    # key 고정 — Streamlit이 매 rerun마다 이 컴포넌트를 같은 인스턴스로 취급해
    # Plotly.react(데이터만 갱신)를 쓰게 강제한다. key 없으면(또는 위치가
    # 흔들리면) 리마운트로 취급돼 지도가 매번 처음부터 다시 그려질 수 있다.
    st.plotly_chart(fig, width="stretch", config={"responsive": True}, key="seoul_map")


# 지도를 뷰포트 전체로 채우고, 입력 패널은 우측에 뜬 반투명 오버레이로 띄운다.
# panel은 position:fixed라 문서 흐름과 무관하게 항상 우측 상단에 고정된다 —
# 그래서 지도(정상 흐름)를 어디서 그리든 패널이 그 위에 뜬다.
FULLSCREEN_CSS = """
<style>
[data-testid="stHeader"] { display: none; }
[data-testid="stAppViewContainer"], [data-testid="stMain"] { padding: 0 !important; }
.block-container { padding: 0 !important; max-width: 100% !important; }
/* 지도(js-plotly-plot) 자체는 100vh로 늘렸지만, Streamlit이 최초 렌더 크기
   (fig.layout.height=760)로 고정 inline height를 박아둔 조상 div들이 그대로
   남아 있어서 그 아래로 빈 칸이 생겼다 — 그 조상들만 콕 집어 같이 늘린다. */
[data-testid="stElementContainer"]:has(.js-plotly-plot),
[data-testid="stFullScreenFrame"]:has(.js-plotly-plot),
[data-testid="stVerticalBlock"]:has(.js-plotly-plot),
[data-testid="stMainBlockContainer"]:has(.js-plotly-plot),
[data-testid="stPlotlyChart"] {
    /* Streamlit이 flex-basis(예: 760px)를 height보다 우선 적용해두는 flex
       레이아웃이라, height만으로는 안 늘어난다 — flex도 같이 덮어써야 한다. */
    width: 100vw !important; height: 100vh !important;
    flex: 1 1 auto !important;
}
[data-testid="stVerticalBlock"]:has(.js-plotly-plot) {
    /* 같은 블록의 형제 요소(숨겨진 CSS 마크다운, position:fixed 패널)와의
       flex gap이 지도 높이만큼 빈 칸으로 남는 걸 막는다. */
    gap: 0 !important;
}
[data-testid="stPlotlyChart"] > div, .js-plotly-plot, .plot-container {
    width: 100vw !important; height: 100vh !important;
}
.st-key-panel {
    position: fixed; top: 0; right: 0;
    width: 400px; height: 100vh; overflow-y: auto;
    z-index: 1000;
    background: rgba(15, 16, 20, 0.82);
    backdrop-filter: blur(10px);
    padding: 1.4rem 1.2rem;
    box-shadow: -6px 0 24px rgba(0, 0, 0, 0.45);
    /* 패널 자체에는 글자색을 안 건다 — text_area 등 입력 위젯은 자기 색을
       따로 안 갖고 이 컨테이너에서 상속받는데, 여기서 강제로 밝게 고정하면
       "밝은 입력창 배경(라이트 테마) + 밝은 글자"가 겹쳐 타이핑한 글자가
       안 보이는 버그가 난다(직접 타이핑해 재현·확인함 — placeholder는
       별도 스타일이라 멀쩡해 보여서 처음엔 못 잡았던 버그). 배경이 항상
       어두운 건 이 패널뿐이고 입력창 자체 배경은 테마를 그대로 따라가므로,
       입력창 글자색도 강제하지 않고 테마 기본값(자기 배경과 이미 짝지어짐)에
       맡긴다. */
}
/* 패널 배경(항상 어두움) 위에 직접 얹히는 순수 텍스트만 밝은 색으로 강제
   고정한다 — 위젯 라벨(stWidgetLabel), 본문/캡션(stMarkdownContainer/
   stCaptionContainer), 제목(stHeading), trace 텍스트(stText)가 여기 해당한다.
   text_area·multiselect·selectbox·number_input 등 입력 위젯은 제외한다 —
   자기 자신의 입력창/드롭다운 배경(테마별로 밝거나 어두움)을 따로 갖고
   있어서, 강제로 밝게 고정하면 자기 배경과 안 맞아 오히려 안 보이게 된다. */
.st-key-panel [data-testid="stWidgetLabel"],
.st-key-panel [data-testid="stMarkdownContainer"],
.st-key-panel [data-testid="stCaptionContainer"],
.st-key-panel [data-testid="stHeading"],
.st-key-panel [data-testid="stText"] {
    color: #f5f5f7;
}
/* 버그: 추천 실행 후 패널 콘텐츠(메시지+필터 검증 expander+trace 텍스트)가
   늘어나 100vh를 넘으면, 브라우저가 스크롤 대신 일부 위젯을 찌그러뜨려
   "추천받기" 버튼이 안 보이게 사라지는 현상이 있었다(직접 재현·확인함).
   원인은 CSS 플렉스박스 스펙: overflow가 visible이 아닌 flex item의
   "자동 최소 크기"는 콘텐츠 크기가 아니라 0으로 계산된다 — text_area
   내부 wrapper(baseweb 구현)가 overflow:auto라 이 규칙에 걸린다. 패널
   안 모든 항목에 flex-shrink:0을 걸어 원래 크기를 지키게 하면, 넘치는
   만큼은 위에 이미 걸어둔 overflow-y:auto가 스크롤로 처리한다. */
.st-key-panel [data-testid="stElementContainer"],
.st-key-panel [data-testid="stVerticalBlock"] {
    flex-shrink: 0 !important;
}
</style>
"""


def _resolve_near_clause(
    place_text: str, radius_km: float | None = None
) -> tuple[FilterClause | None, dict | None]:
    """기준 장소 입력 → (FilterClause, 지도 미리보기 핀). 후보가 여러 개면
    라디오로 직접 고르게 하고, 고른 좌표를 FilterClause.lon/lat에 그대로
    담는다 — tools.py가 이 좌표를 쓰면 place로 재검색하지 않으므로, "삼성"
    같은 흔한 이름이 Kakao 자체 top-1(사용자가 고른 것과 다를 수 있음)으로
    바뀌는 일이 없다. Kakao 키가 없거나 검색 결과가 없어도 place만 담은
    FilterClause를 반환해 tools.py의 기존 unresolved_requirements 보고
    경로를 그대로 재사용한다(여기서 별도로 "못 찾음" 처리를 만들지 않는다).
    radius_km은 그대로 FilterClause.radius_km에 실어, tools.py가 기본값
    (3km) 대신 사용자가 고른 반경으로 거리 필터를 적용하게 한다."""
    place_text = place_text.strip()
    if not place_text:
        return None, None

    repo = get_hybrid_facility_repository()
    if not repo.near_resolvable():
        st.caption("⚠ Kakao API 키가 없어 장소 검색을 쓸 수 없습니다.")
        return FilterClause(type="near", place=place_text, radius_km=radius_km), None

    candidates = repo.search_place_candidates(place_text)
    if not candidates:
        st.caption("검색 결과가 없습니다. 다른 이름으로 시도해보세요.")
        return FilterClause(type="near", place=place_text, radius_km=radius_km), None

    def _label(i: int) -> str:
        c = candidates[i]
        return f"{c['name']} ({c['address']})" if c["address"] else c["name"]

    chosen_idx = st.radio(
        "검색 결과 — 원하는 곳을 고르세요", range(len(candidates)),
        format_func=_label, key=f"place_radio::{place_text}",
    )
    chosen = candidates[chosen_idx]
    clause = FilterClause(
        type="near", place=chosen["name"], lon=chosen["lon"], lat=chosen["lat"],
        radius_km=radius_km)
    preview_point = {
        "label": f"{chosen['name']} (미리보기)", "lon": chosen["lon"], "lat": chosen["lat"],
        "kind": "preview",
    }
    return clause, preview_point


@st.fragment
def _app_body(geojson: dict) -> None:
    """앱 전체를 프래그먼트 하나로 감싼다.

    Streamlit은 위젯(텍스트 입력 blur, 셀렉트박스, 체크박스) 하나만 바뀌어도
    스크립트 전체를 처음부터 다시 실행하는 게 기본 동작이다. run_agent_cached/
    load_boundaries 등은 이미 st.cache_data라 재계산 자체는 공짜지만, "전체
    재실행"이라는 오버헤드 자체는 그대로 남는다. 위젯을 만드는 코드를 전부
    이 프래그먼트 안에 두면, 그중 뭘 누르든 이 함수만 다시 실행되고 바깥
    main()은 두 번 다시 돌지 않는다 — 그래서 매번 "처음부터" 도는 느낌이
    사라진다. (Streamlit 정책상 프래그먼트가 만든 위젯은 프래그먼트 밖에서
    만든 컨테이너에 못 넣으므로, panel 컨테이너도 이 안에서 새로 만든다.)

    단, 지도가 확대·이동해둔 위치까지 지켜주진 못한다 — Streamlit이 Plotly
    지도를 내용(색·핀)이 바뀔 때마다 완전히 새 컴포넌트로 마운트하는 동작이라
    (uirevision을 걸어도 이 조합에서는 카메라가 리셋됨, 직접 확인함), 그건
    커스텀 JS 브릿지 없이는 못 고치는 프레임워크 한계로 받아들인다.

    st.button()은 그 버튼이 눌린 단 한 번의 rerun에서만 True를 반환하고,
    그 외 모든 rerun(다른 위젯 조작·재입력 중 blur)에서는 False다. 그래서
    "입력이 있으면 무조건 실행"이 아니라 "버튼을 누른 rerun에서만 실행"으로
    게이트를 걸 수 있다. 계산 결과는 session_state["last_result"]에 저장해,
    버튼을 안 누른 rerun에서도 마지막 추천/지도를 계속 보여준다.

    구·기준 장소는 버튼을 누르기 전에도 지도에 미리보기로 반영된다(선택할
    때마다 preview_points가 즉시 다시 계산되므로) — LLM 호출 없이 순수
    프론트 상태만으로 되는 부분이라 버튼 게이트와 무관하게 항상 최신이다.
    """
    panel = st.container(key="panel")
    with panel:
        st.subheader("살래말래")
        st.caption("자유롭게 적은 내용은 선호로 반영되고, 자치구·이 장소 근처만 보기(옵션)는 하드 필터로 적용됩니다.")
        if using_mock_llm():
            st.caption(f"⚠ Mock LLM으로 동작 중 ({_mock_llm_reason()})")

        preference_text = st.text_area(
            "어떤 동네를 찾으세요?",
            placeholder="예: 안전하고 조용한 곳, 지하철 가까운 곳, 헬스장 있으면 좋겠어요",
            height=150,
        )

        st.markdown("**옵션 — 조건으로 좁히기**")
        gu_selected = st.multiselect(
            "자치구 선택하기", SEOUL_GU, help="선택한 자치구 안에서만(또는 제외하고) 찾습니다.")
        gu_exclude = st.checkbox(
            "선택한 자치구 제외하기", value=False,
            help="체크하면 선택한 자치구를 뺀 나머지 지역에서만 찾습니다.")
        place_col, radius_col, search_col = st.columns([3, 1.2, 1])
        with place_col:
            place_text = st.text_input(
                "이 장소 근처만 보기", placeholder="예: 서울대병원, 강남역, 성남시청, 주소 등")
        with radius_col:
            radius_km = st.number_input(
                "반경(km)", min_value=0.5, max_value=50.0, value=3.0, step=0.5,
                help="선택한 장소에서 이 거리 이내 동만 통과시킵니다.")
        with search_col:
            st.markdown("<div style='height:1.85rem'></div>", unsafe_allow_html=True)
            st.button("검색", type="primary", width="stretch")
        near_clause, preview_point = _resolve_near_clause(place_text, radius_km)

        submitted = st.button("동네 추천하기", width="stretch", type="primary")
        message_slot = st.empty()
        style_name = st.selectbox(
            "지도 스타일", list(MAP_STYLES), index=list(MAP_STYLES).index(DEFAULT_MAP_STYLE))
        show_core = st.checkbox("서울 핵심시설 표시", value=True)
    map_kw = dict(map_style=MAP_STYLES[style_name], show_core=show_core)
    preview_points = [preview_point] if preview_point else []

    required_filters: list[FilterClause] = []
    if gu_selected:
        required_filters.append(FilterClause(type="gu", gu=list(gu_selected), exclude=gu_exclude))
    if near_clause is not None:
        required_filters.append(near_clause)

    # 버튼을 누른 rerun에서만 LLM을 호출한다 — 그 외의 rerun(다른 위젯 조작,
    # 텍스트 입력 중 blur)은 session_state에 저장해둔 마지막 결과를 그대로 쓴다.
    is_empty_submit = submitted and not preference_text.strip() and not required_filters
    if submitted and not is_empty_submit:
        required_filters_json = json.dumps(
            [c.model_dump(exclude_none=True) for c in required_filters])
        st.session_state["last_result"] = run_agent_cached(
            preference_text, using_mock_llm(), PIPELINE_VERSION, required_filters_json)

    if is_empty_submit:
        message_slot.info("내용을 입력하거나 자치구·이 장소 근처만 보기 중 하나 이상 지정한 뒤 눌러주세요.")

    result = st.session_state.get("last_result")
    if result is None:
        render_map(neutral_dataframe(geojson), geojson, points=preview_points, **map_kw)
        return

    if result["kind"] == "clarify":
        if not is_empty_submit:
            message_slot.warning(result["message"])
        render_map(neutral_dataframe(geojson), geojson, points=preview_points, **map_kw)
        return

    if not is_empty_submit:
        message_slot.success(result["message"])
    data = result["data"]
    if data.get("unresolved_requirements"):
        with panel:
            st.warning("해석하지 못한 필수 조건 (필터 미적용): "
                       + ", ".join(data["unresolved_requirements"]))
    df = assign_tiers(data["recommendations"], data.get("disqualified", []))
    centroids = dong_centroids(geojson)
    top3_points = [
        {"label": f"{rec['gu']} {rec['dong']}", "lon": centroids[rec["scores"]["code"]][0],
         "lat": centroids[rec["scores"]["code"]][1], "kind": "top3"}
        for rec in data["recommendations"][:3] if rec["scores"]["code"] in centroids
    ]
    render_map(df, geojson, points=(data.get("map_points") or []) + preview_points + top3_points, **map_kw)

    with panel, st.expander("🔍 적용된 필터 검증"):
        st.caption(f"추천 {len(data['recommendations'])}개 / "
                   f"실격 {len(data.get('disqualified', []))}개 "
                   f"(파이프라인 v{PIPELINE_VERSION})")
        for line in result["trace"]:
            st.text(line)


def main() -> None:
    geojson = load_boundaries()
    st.markdown(FULLSCREEN_CSS, unsafe_allow_html=True)
    _app_body(geojson)


if __name__ == "__main__":
    main()
