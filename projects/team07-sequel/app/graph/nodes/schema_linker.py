"""schema_link 노드 — 정규화된 질문/키워드로 스키마·값을 링크한다.

관련 테이블만 임베딩으로 축소하고(schema_retriever; 소형 스키마는 전체 사용),
키워드를 실제 DB 값으로 확정한다(value_retriever). 여기에 오프라인 컬럼 설명
(metadata_repository)과 few-shot 예시(example_repository)까지 붙여
SQL 생성이 "작고 정확하며 근거 있는 컨텍스트"를 보게 한다.
(BIRD ablation: metadata·few-shot 이 정확도 상위 2개 레버)

입력(state): normalized_question(없으면 question), keywords, time_range
출력(state): schema(DDL+조인+컬럼설명+값힌트+기간), tables, joins, value_hints, unresolved, fewshot
"""
from app.core.settings import settings
from app.graph.state import AgentState
from app.repositories.example_repository import retrieve_examples
from app.repositories.metadata_repository import mschema
from app.tools.schema_retriever import retrieve_schema
from app.tools.value_retriever import retrieve_values


def schema_link(state: AgentState) -> dict:
    question = state.get("normalized_question") or state["question"]
    keywords = state.get("keywords") or []

    schema_res = retrieve_schema(question)
    value_res = retrieve_values(keywords, schema_res.tables)

    # 메타데이터 있으면 M-Schema(컬럼당 한 줄: 타입+설명+예시)가 DDL 을 대체 — 토큰↓·정확도↑.
    # 없는 DB(평가용 sqlite 등)는 기존 DDL 그대로.
    parts = [mschema(schema_res.tables) or schema_res.ddl]
    if schema_res.joins:
        parts.append("# 조인 경로\n" + "\n".join(schema_res.joins))
    # 프롬프트 주입은 문자 일치(exact/synonym) 확정만. 유사도 기반(embedding·fuzzy·ambiguous)은
    # 프롬프트에 넣지 않는다(state.value_hints 로만 보존 — 되묻기 UX용).
    # 근거(한국어 1200 전수): 확정 주입 시 -17.8pp, "후보(단정금지)" 프레이밍으로도 -9.4pp 잔존
    # → 불확실 힌트는 어떤 프레이밍으로도 생성기를 오도함. MapleRepair 의 selective 원칙과 동일.
    confident = [h for h in value_res.hints if h.how in ("exact", "synonym")]
    if confident:
        parts.append("# 값 매칭 (확정)\n" + "\n".join(
            f"{h.keyword} → {h.column} = {h.value} ({h.how})" for h in confident))
    time_range = state.get("time_range") or {}
    if time_range:
        parts.append(f"# 기간\n{time_range.get('start')} ~ {time_range.get('end')}")

    return {
        "schema": "\n\n".join(parts),
        "tables": schema_res.tables,
        "joins": schema_res.joins,
        "value_hints": [h.model_dump() for h in value_res.hints],
        "unresolved": value_res.unresolved,
        # route(난이도 확정)가 이 노드 뒤라 실제 k 를 아직 모름 → 최댓값 확보,
        # generator 가 state["difficulty"] 로 필요한 만큼만 슬라이싱.
        "fewshot": retrieve_examples(question, settings.fewshot_k_max),
    }
