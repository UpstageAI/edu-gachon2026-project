"""리뷰 파이프라인 전체를 "그래프"로 엮어 실행하는 핵심 모듈.

리뷰는 여러 단계를 순서대로 거친다. 이 파일은 그 단계들을 LangGraph의
StateGraph(상태를 들고 노드에서 노드로 흐르는 그래프)로 구성한다. 각 노드는
"상태(state) 사전을 받아 일부를 갱신해 돌려주는 함수"다. 대략의 흐름:

  특징 추출 → 라우팅 → 복잡도 분석 → 하네스 선택 → (정책 검색 or 생략)
  → 프롬프트 생성 → LLM 호출 → finding 검증 → 결과 조립 → 저장 → 댓글 게시 → 완료

핵심 구성:
- ReviewWorkflowState : 그래프가 들고 다니는 상태의 형태(TypedDict).
- ReviewWorkflowGraph : 위 단계들을 노드/엣지로 조립하고 실행하는 클래스.
- 파일 상단의 fallback StateGraph / _LocalCompiledGraph : LangGraph 패키지가
  설치돼 있지 않을 때를 대비한 "직접 만든 대체 구현"이다. 아래 try/except 참고.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, TypedDict

from backend.app.core.routing import extract_features, select_route
from backend.app.core.schemas import (
    ComplexityMetric,
    FileChangeSummary,
    JsonDict,
    ModelCallUsage,
    PolicyChunk,
    PullRequestFeatures,
    ReviewHarnessContext,
    ReviewFinding,
    ReviewRequest,
    ReviewResult,
    ReviewRoute,
    ReviewSummary,
)
from backend.app.services.llm import LLMClient
from backend.app.services.policy_harness import PolicyHarness
from backend.app.services.prompt_builder import ReviewPromptBatch, build_review_prompt_batches
from backend.app.services.publisher import ReviewPublisher
from backend.app.services.rag import LocalPolicyIndex
from backend.app.services.rag import rank_policy_chunks
from backend.app.services.review_quality import validate_and_rank_findings
from backend.app.storage.factory import ReviewStore
from review_harness.scripts.complexity_metrics import analyze_complexity

# LangGraph가 설치돼 있으면 진짜 구현을 쓰고, 없으면(ImportError) 아래에서 최소 기능만
# 흉내 낸 대체 구현을 정의한다. 이렇게 하면 이 코드는 LangGraph 없이도 돌아간다.
try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - 배포 환경에서는 pyproject 의존성으로 설치된다.
    # START/END는 그래프의 "시작"과 "끝"을 가리키는 특별한 표식(문자열이면 충분하다).
    END = "__end__"
    START = "__start__"
    LANGGRAPH_AVAILABLE = False

    # 아래 두 클래스는 LangGraph의 StateGraph API를 흉내 낸 축소판이다. 실제 라이브러리와
    # 똑같은 메서드 이름(add_node/add_edge/compile/invoke 등)을 제공해, 아래쪽 그래프
    # 조립 코드가 LangGraph 유무와 상관없이 똑같이 동작하도록 만든다.
    class StateGraph:  # type: ignore[no-redef]
        """노드(단계)와 엣지(연결)를 모아 두었다가 compile()로 실행기를 만드는 설계도.

        add_node로 "이름->함수"를, add_edge로 "A 다음엔 B"를 등록한다.
        add_conditional_edges는 상태를 보고 다음 노드를 고르는 분기(조건 엣지)다.
        """

        def __init__(self, state_schema: type[TypedDict]) -> None:
            # 이름 -> 노드 함수. 각 노드는 상태 dict를 받아 갱신할 dict(또는 None)를 낸다.
            self.nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {}
            # 노드 -> 다음에 갈 노드들의 목록(일반 연결).
            self.edges: dict[str, list[str]] = {}
            # 노드 -> (분기 함수, 결과값->노드 이름 매핑). 조건에 따라 다음 노드가 갈린다.
            self.conditional_edges: dict[
                str,
                tuple[Callable[[dict[str, Any]], str], dict[str, str]],
            ] = {}

        def add_node(self, name: str, node: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
            self.nodes[name] = node

        def add_edge(self, source: str, target: str) -> None:
            # setdefault: source 키가 없으면 빈 리스트로 시작한 뒤 target을 덧붙인다.
            self.edges.setdefault(source, []).append(target)

        def add_conditional_edges(
            self,
            source: str,
            path: Callable[[dict[str, Any]], str],
            path_map: list[str] | dict[str, str],
        ) -> None:
            # path_map이 리스트면 "결과값 그대로가 노드 이름"인 매핑으로 바꿔 준다.
            if isinstance(path_map, list):
                resolved_path_map = {item: item for item in path_map}
            else:
                resolved_path_map = path_map
            self.conditional_edges[source] = (path, resolved_path_map)

        def compile(self) -> "_LocalCompiledGraph":
            # 설계도를 실제로 실행할 수 있는 형태로 굳힌다(LangGraph의 compile과 같은 개념).
            return _LocalCompiledGraph(self.nodes, self.edges, self.conditional_edges)


    class _LocalCompiledGraph:
        """compile()이 만들어 내는 "완성된 그래프". invoke()로 실제 실행한다.

        START에서 시작해 엣지를 따라 노드를 하나씩 실행하며, 각 노드가 돌려준 값으로
        상태를 갱신한다. 조건 엣지를 만나면 분기 함수 결과로 다음 노드를 고른다.
        END를 만나면 멈춘다. 이것이 LangGraph 실행의 아주 단순화된 버전이다.
        """

        def __init__(
            self,
            nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]],
            edges: dict[str, list[str]],
            conditional_edges: dict[
                str,
                tuple[Callable[[dict[str, Any]], str], dict[str, str]],
            ],
        ) -> None:
            self.nodes = nodes
            self.edges = edges
            self.conditional_edges = conditional_edges

        def invoke(self, input_state: dict[str, Any]) -> dict[str, Any]:
            # 입력을 복사해 시작 상태로 삼는다(원본 훼손 방지).
            state = dict(input_state)
            # START에서 이어지는 노드들을 처리 대기열에 넣는다.
            next_nodes = list(self.edges.get(START, []))
            while next_nodes:
                node_name = next_nodes.pop(0)  # 대기열 맨 앞을 꺼낸다.
                if node_name == END:
                    continue
                # 노드를 실행하고, 돌려준 갱신값(없으면 {})으로 상태를 합친다.
                update = self.nodes[node_name](state) or {}
                state.update(update)
                if node_name in self.conditional_edges:
                    # 조건 엣지: 분기 함수(path)의 결과로 다음 노드 하나를 고른다.
                    path, path_map = self.conditional_edges[node_name]
                    target = path_map[path(state)]
                    next_nodes = [] if target == END else [target]
                else:
                    # 일반 엣지: END를 뺀 다음 노드들로 대기열을 교체한다(리스트 컴프리헨션).
                    next_nodes = [target for target in self.edges.get(node_name, []) if target != END]
            return state


# TypedDict = "이런 키에는 이런 타입"이라고 정해 둔 딕셔너리. total=False는 "모든 키가
# 항상 있는 건 아니다"라는 뜻으로, 단계가 진행되며 키가 하나씩 채워지기 때문이다.
# 이 상태(state)가 노드에서 노드로 전달되며 리뷰 결과가 점점 쌓인다.
class ReviewWorkflowState(TypedDict, total=False):
    review_run_id: str
    request: ReviewRequest
    policy_available: bool
    features: PullRequestFeatures
    route: ReviewRoute
    complexity_metrics: list[ComplexityMetric]
    policies: list[PolicyChunk]
    review_harness: ReviewHarnessContext
    prompt_batches: list[ReviewPromptBatch]
    summary: ReviewSummary
    findings: list[ReviewFinding]
    finding_validation: JsonDict
    usage: ModelCallUsage
    result: ReviewResult
    publish_result: dict[str, object]


def langgraph_runtime_name() -> str:
    """지금 진짜 LangGraph를 쓰는지, 대체 구현을 쓰는지 이름으로 알려 준다(이벤트 기록용)."""
    return "langgraph" if LANGGRAPH_AVAILABLE else "local_fallback"


class ReviewWorkflowGraph:
    """리뷰 단계들을 노드/엣지로 조립하고 실행하는 클래스.

    __init__에서 필요한 부품(정책 인덱스, LLM, 게시기, 저장소, 하네스)을 받아 두고
    그래프를 미리 만든다(_build_graph). run()이 실제 실행 진입점이다. 아래의
    _로 시작하는 메서드들이 각각 그래프의 노드 하나에 대응한다.
    """

    def __init__(
        self,
        policy_index: LocalPolicyIndex,
        llm_client: LLMClient,
        publisher: ReviewPublisher,
        store: ReviewStore,
        policy_harness: PolicyHarness,
        event_publisher: Callable[[str, JsonDict | None], object] | None = None,
    ) -> None:
        self.policy_index = policy_index
        self.llm_client = llm_client
        self.publisher = publisher
        self.store = store
        self.policy_harness = policy_harness
        self.event_publisher = event_publisher
        self.graph = self._build_graph()

    def run(self, request: ReviewRequest, review_run_id: str) -> ReviewResult:
        """리뷰 요청을 초기 상태로 넣어 그래프를 끝까지 돌리고 최종 결과를 꺼낸다."""
        final_state = self.graph.invoke(
            {
                "review_run_id": review_run_id,
                "request": request,
            }
        )
        # 마지막 노드까지 실행되면 상태의 "result" 키에 최종 ReviewResult가 들어 있다.
        return final_state["result"]

    def _build_graph(self):
        """단계(노드)들과 그 순서(엣지)를 등록해 실행 가능한 그래프로 컴파일한다.

        add_node로 각 단계를 이름과 함께 등록하고, add_edge로 "A 다음 B"를 잇는다.
        select_harness 다음만 조건 분기(정책 검색을 할지 말지)라 별도로 처리한다.
        """
        graph = StateGraph(ReviewWorkflowState)
        graph.add_node("create_review", self._create_review)
        graph.add_node("extract_features", self._extract_features)
        graph.add_node("select_route", self._select_route)
        graph.add_node("analyze_complexity", self._analyze_complexity)
        graph.add_node("select_harness", self._select_harness)
        graph.add_node("retrieve_policies", self._retrieve_policies)
        graph.add_node("skip_policy_retrieval", self._skip_policy_retrieval)
        graph.add_node("build_prompt", self._build_prompt)
        graph.add_node("call_llm", self._call_llm)
        graph.add_node("validate_findings", self._validate_findings)
        graph.add_node("assemble_result", self._assemble_result)
        graph.add_node("persist_result", self._persist_result)
        graph.add_node("publish_comment", self._publish_comment)
        graph.add_node("complete_review", self._complete_review)

        # 아래는 단계 간 연결이다. 순서대로 흐르며, 앞 단계 결과를 다음 단계가 이어받는다.
        graph.add_edge(START, "create_review")
        graph.add_edge("create_review", "extract_features")
        graph.add_edge("extract_features", "select_route")
        graph.add_edge("select_route", "analyze_complexity")
        graph.add_edge("analyze_complexity", "select_harness")
        # 조건 분기: route가 RAG를 쓰면 "retrieve"(정책 검색), 아니면 "skip"으로 간다.
        graph.add_conditional_edges(
            "select_harness",
            self._policy_retrieval_path,
            {
                "retrieve": "retrieve_policies",
                "skip": "skip_policy_retrieval",
            },
        )
        graph.add_edge("retrieve_policies", "build_prompt")
        graph.add_edge("skip_policy_retrieval", "build_prompt")
        graph.add_edge("build_prompt", "call_llm")
        graph.add_edge("call_llm", "validate_findings")
        graph.add_edge("validate_findings", "assemble_result")
        graph.add_edge("assemble_result", "persist_result")
        graph.add_edge("persist_result", "publish_comment")
        graph.add_edge("publish_comment", "complete_review")
        graph.add_edge("complete_review", END)
        return graph.compile()

    def _publish(self, event_type: str, payload: JsonDict | None = None) -> None:
        # 진행 상황 이벤트를 바깥으로 흘려보낸다. 콜백이 없으면 조용히 넘어간다.
        if self.event_publisher:
            self.event_publisher(event_type, payload or {})

    # --- 아래부터 각 메서드가 그래프의 노드 하나다. 모두 state를 받아 갱신할 dict를 낸다. ---

    def _create_review(self, state: ReviewWorkflowState) -> JsonDict:
        """[1단계] 리뷰 시작을 알리는 이벤트만 발행한다(상태 갱신 없음)."""
        request = state["request"]
        self._publish(
            "review_created",
            {
                "repository": request.repository.full_name,
                "pull_request_number": request.pull_request.number,
                "head_sha": request.pull_request.head_sha,
                "workflow_engine": langgraph_runtime_name(),
            },
        )
        return {}

    def _extract_features(self, state: ReviewWorkflowState) -> JsonDict:
        """[2단계] PR에서 라우팅용 특징을 뽑고, 정책 사용 가능 여부를 판단한다."""
        request = state["request"]
        # 요청에 정책이 딸려 왔거나 인덱스에 정책이 있으면 RAG를 쓸 수 있다.
        policy_available = bool(request.repository_policies) or self.policy_index.has_policy()
        features = extract_features(request, policy_available=policy_available)
        self._publish("features_extracted", features.to_dict())
        return {"policy_available": policy_available, "features": features}

    def _select_route(self, state: ReviewWorkflowState) -> JsonDict:
        """[3단계] 특징을 보고 리뷰 경로(저비용/표준/심층)를 고른다."""
        route = select_route(state["features"], review_mode=state["request"].review_mode)
        self._publish("route_selected", route.to_dict())
        return {"route": route}

    def _analyze_complexity(self, state: ReviewWorkflowState) -> JsonDict:
        """[4단계] Radon으로 함수별 순환 복잡도 변화를 측정해 요청에 붙인다."""
        request = state["request"]
        metrics = analyze_complexity(request)
        # frozen dataclass라 직접 못 바꾸므로 replace로 metrics를 채운 복사본을 만든다.
        request = replace(request, complexity_metrics=metrics)
        self._publish(
            "complexity_analyzed",
            {
                "tool": "radon",
                "metric": "cyclomatic_complexity",
                "measured_count": len(metrics),
                # bool을 sum하면 True=1로 세어져 "임계값 초과 개수"가 된다.
                "threshold_exceeded_count": sum(
                    metric.exceeded_threshold for metric in metrics
                ),
                # {...} = 집합 컴프리헨션. 파일 경로 중복을 없앤 뒤 정렬한다.
                "files": sorted({metric.file_path for metric in metrics}),
            },
        )
        return {"request": request, "complexity_metrics": metrics}

    def _policy_retrieval_path(self, state: ReviewWorkflowState) -> str:
        """조건 분기 함수: route가 RAG를 쓰면 정책 검색, 아니면 생략으로 보낸다."""
        return "retrieve" if state["route"].use_rag else "skip"

    def _select_harness(self, state: ReviewWorkflowState) -> JsonDict:
        """[5단계] PR 신호에 맞는 검토 하네스(skill/지식 카드/정책 유형)를 고른다."""
        context = self.policy_harness.select(state["request"], state["route"])
        self._publish(
            "review_harness_selected",
            {
                "version": context.version,
                "signals": sorted(context.signals),
                "skills": [skill.skill_id for skill in context.skills],
                "knowledge_cards": [card.card_id for card in context.knowledge_cards],
                "policy_types": context.policy_types,
                "candidate_policy_types": context.candidate_policy_types,
            },
        )
        return {"review_harness": context}

    def _retrieve_policies(self, state: ReviewWorkflowState) -> JsonDict:
        """[6-A단계] 저장소 정책을 검색·랭킹해 상위 조각을 프롬프트에 쓸 재료로 모은다."""
        context = state["review_harness"]
        self._publish(
            "policy_retrieval_started",
            {"candidate_top_k": 8, "policy_types": context.candidate_policy_types},
        )
        # 인덱스에서 관련 정책 조각을 검색한다. set(...) or None: 후보 유형이 있으면
        # 그 유형으로 필터링하고, 비어 있으면 None(=필터 없음)을 넘긴다.
        indexed_policies = self.policy_index.search(
            state["request"],
            top_k=8,
            policy_types=set(context.candidate_policy_types) or None,
        )
        # 요청에 딸려 온 정책과 검색된 정책을 합쳐(*로 두 리스트를 펼침) 관련도 순으로
        # 다시 랭킹하고 상위 8개만 남긴다.
        policies = rank_policy_chunks(
            [*state["request"].repository_policies, *indexed_policies],
            state["request"],
            top_k=8,
            policy_types=set(context.candidate_policy_types) or None,
        )
        self._publish(
            "policy_retrieval_completed",
            {
                "retrieved_count": len(policies),
                "sources": [policy.source_path for policy in policies],
            },
        )
        return {"policies": policies}

    def _skip_policy_retrieval(self, state: ReviewWorkflowState) -> JsonDict:
        """[6-B단계] RAG를 안 쓰는 경로일 때 정책 검색을 건너뛰고 빈 목록을 남긴다."""
        self._publish("policy_retrieval_skipped", {"reason": "route does not require rag"})
        return {"policies": []}

    def _build_prompt(self, state: ReviewWorkflowState) -> JsonDict:
        """[7단계] 요청/정책/하네스로 LLM 프롬프트를 만든다. 큰 PR은 여러 배치로 쪼갠다.

        배치마다 실제로 쓰인 정책/skill/카드를 모아, 결과에 기록할 "적용된 하네스"를
        다시 조립한다. 최종적으로 프롬프트 배치와 실제 사용된 정책 목록을 상태에 넣는다.
        """
        batches = build_review_prompt_batches(
            state["request"],
            state["route"],
            state["policies"],
            policy_harness=self.policy_harness,
        )
        # 여러 배치에 흩어진 정책/skill/카드를 딕셔너리에 모아 중복 없이 합친다
        # (같은 키면 덮어써져 자연스럽게 유일해진다).
        selected_policies: dict[tuple[str, str], PolicyChunk] = {}
        selected_skills = {}
        selected_knowledge_cards = {}
        for batch in batches:
            for policy in batch.policies:
                selected_policies[(policy.source_path, policy.section_title)] = policy
            if batch.harness:
                for skill in batch.harness.skills:
                    selected_skills[skill.skill_id] = skill
                for card in batch.harness.knowledge_cards:
                    selected_knowledge_cards[card.card_id] = card
        harness = state["review_harness"]
        # 실제로 프롬프트에 쓰인 것들로 하네스를 다시 만든다. (A or B): 실제 쓰인 게
        # 비어 있으면 원래 하네스 값으로 대체(fallback).
        applied_harness = ReviewHarnessContext(
            version=harness.version,
            signals=harness.signals,
            skills=list(selected_skills.values()) or harness.skills,
            knowledge_cards=(
                list(selected_knowledge_cards.values()) or harness.knowledge_cards
            ),
            # 중첩 집합 컴프리헨션: 쓰인 skill들이 다루는 정책 유형을 모두 모아
            # 중복을 없애고 정렬한다(바깥 for가 먼저, 안쪽 for가 나중).
            policy_types=sorted(
                {
                    policy_type
                    for skill in (list(selected_skills.values()) or harness.skills)
                    for policy_type in skill.policy_types
                }
            ),
            candidate_policy_types=harness.candidate_policy_types,
        )
        self._publish(
            "prompt_built",
            {
                "batch_count": len(batches),
                "selected_files": sum(len(batch.request.changed_files) for batch in batches),
                "patch_chars": sum(batch.patch_chars for batch in batches),
                "skills": [skill.skill_id for skill in applied_harness.skills],
                "knowledge_cards": [
                    card.card_id for card in applied_harness.knowledge_cards
                ],
                "policies_per_batch": [len(batch.policies) for batch in batches],
            },
        )
        return {
            "prompt_batches": batches,
            "policies": list(selected_policies.values()),
            "review_harness": applied_harness,
        }

    def _call_llm(self, state: ReviewWorkflowState) -> JsonDict:
        """[8단계] 각 프롬프트 배치로 모델을 호출하고, 배치 결과를 하나로 합친다.

        배치가 여러 개면 ThreadPoolExecutor로 병렬 호출해 시간을 줄인다. 이후 여러
        배치의 요약(summary)/지적(findings)/사용량(usage)을 합쳐 하나로 만든다.
        """
        route = state["route"]
        batches = state["prompt_batches"]
        self._publish(
            "llm_call_started",
            {
                "model_tier": route.model_tier,
                "route_name": route.name,
                "batch_count": len(batches),
            },
        )
        for batch in batches:
            self._publish(
                "llm_batch_started",
                {
                    "batch_index": batch.index,
                    "batch_count": batch.count,
                    "files_count": len(batch.request.changed_files),
                    "patch_chars": batch.patch_chars,
                    "skills": (
                        [skill.skill_id for skill in batch.harness.skills]
                        if batch.harness
                        else []
                    ),
                    "knowledge_cards": (
                        [card.card_id for card in batch.harness.knowledge_cards]
                        if batch.harness
                        else []
                    ),
                    "policy_sources": [
                        f"{policy.source_path}#{policy.section_title}"
                        for policy in batch.policies
                    ],
                },
            )

        # 배치 하나를 모델에 보내 (요약, findings, usage) 튜플을 받는 내부 함수.
        def generate(batch: ReviewPromptBatch):
            return self.llm_client.generate_review(
                request=batch.request,
                route=route,
                policies=batch.policies,
                messages=batch.messages,
                review_run_id=state["review_run_id"],
                batch_index=batch.index,
                batch_count=batch.count,
            )

        started = time.perf_counter()  # 전체 호출에 걸린 시간을 재기 위한 시작 시각.
        if len(batches) == 1:
            batch_results = [generate(batches[0])]
        else:
            # 배치가 여럿이면 스레드 풀로 동시에 호출한다(최대 4개). with ... as로
            # 블록이 끝나면 스레드가 자동 정리된다. executor.map은 각 배치에 generate를
            # 적용해 결과를 순서대로 돌려준다.
            with ThreadPoolExecutor(max_workers=min(4, len(batches))) as executor:
                batch_results = list(executor.map(generate, batches))
        latency_ms = int((time.perf_counter() - started) * 1000)

        # 각 배치 결과 튜플을 종류별로 분리한다. findings는 중첩 컴프리헨션으로 평탄화
        # (모든 배치의 finding들을 한 리스트로 이어 붙임).
        summaries = [result[0] for result in batch_results]
        findings = [finding for result in batch_results for finding in result[1]]
        usages = [result[2] for result in batch_results]
        # 여러 요약 중 위험도가 가장 높은 것을 대표로 삼는다(max + 위험도 순위표).
        risk_order = {"low": 0, "medium": 1, "high": 2}
        representative = max(
            summaries,
            key=lambda summary: risk_order.get(summary.overall_risk.lower(), 1),
        )
        if len(batches) == 1:
            summary = representative
        else:
            # 여러 배치를 합칠 때: 파일별 요약은 파일 경로 기준으로 하나만 남긴다
            # (setdefault라 먼저 나온 것을 유지).
            file_summaries_by_path: dict[str, FileChangeSummary] = {}
            for batch_summary in summaries:
                for file_summary in batch_summary.file_summaries:
                    file_summaries_by_path.setdefault(file_summary.file_path, file_summary)
            # 변경 요약 문장들은 순서를 지키며 중복 제거한다. dict.fromkeys는 "키의 순서를
            # 보존하는 중복 제거" 관용구다(set과 달리 순서가 유지된다).
            merged_change_summaries = list(
                dict.fromkeys(
                    batch_summary.change_summary.strip()
                    for batch_summary in summaries
                    if batch_summary.change_summary.strip()
                )
            )
            change_summary = " ".join(merged_change_summaries)
            # 너무 길면 잘라 내고 "..."을 붙인다(댓글 길이 제한 대비).
            if len(change_summary) > 1600:
                change_summary = change_summary[:1597].rstrip() + "..."
            summary = ReviewSummary(
                route_name=route.name,
                model_tier=route.model_tier,
                overall_risk=representative.overall_risk,
                short_comment=f"변경 파일 {len(file_summaries_by_path)}개를 검토했습니다.",
                change_summary=change_summary,
                file_summaries=list(file_summaries_by_path.values()),
            )
        # 사용량(토큰/비용)은 모든 배치를 합산한다. provider/model 등은 배치마다 같으므로
        # 첫 배치 값을 대표로 쓴다.
        usage = ModelCallUsage(
            provider=usages[0].provider,
            model=usages[0].model,
            prompt_tokens=sum(item.prompt_tokens for item in usages),
            completion_tokens=sum(item.completion_tokens for item in usages),
            latency_ms=latency_ms,
            status="completed",
            reasoning_effort=usages[0].reasoning_effort,
            cost_usd=sum(item.cost_usd for item in usages),
            batch_count=len(batches),
        )
        # 배치별 완료 이벤트를 발행한다. zip(strict=True)는 두 리스트를 짝지어 돌되,
        # 길이가 다르면 에러를 낸다(짝이 안 맞는 실수를 막는다). (_, ...)의 _는 안 쓰는 값.
        for batch, (_, batch_findings, batch_usage) in zip(batches, batch_results, strict=True):
            self._publish(
                "llm_batch_completed",
                {
                    "batch_index": batch.index,
                    "batch_count": batch.count,
                    "findings_count": len(batch_findings),
                    "prompt_tokens": batch_usage.prompt_tokens,
                    "completion_tokens": batch_usage.completion_tokens,
                    "latency_ms": batch_usage.latency_ms,
                },
            )
        self._publish(
            "llm_call_completed",
            {
                "provider": usage.provider,
                "model": usage.model,
                "reasoning_effort": usage.reasoning_effort,
                "latency_ms": usage.latency_ms,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "batch_count": usage.batch_count,
            },
        )
        return {"summary": summary, "findings": findings, "usage": usage}

    def _validate_findings(self, state: ReviewWorkflowState) -> JsonDict:
        """[9단계] 모델이 낸 지적을 검증·정규화·랭킹한다(review_quality.py에 위임)."""
        findings, report = validate_and_rank_findings(
            request=state["request"],
            route=state["route"],
            policies=state["policies"],
            findings=state["findings"],
            knowledge_cards=state["review_harness"].knowledge_cards,
        )
        self._publish("findings_validated", report)
        return {"findings": findings, "finding_validation": report}

    def _assemble_result(self, state: ReviewWorkflowState) -> JsonDict:
        """[10단계] 지금까지 쌓인 상태 조각들을 최종 ReviewResult 하나로 조립한다."""
        request = state["request"]
        result = ReviewResult(
            review_run_id=state["review_run_id"],
            status="completed",
            idempotency_key=request.idempotency_key(),
            summary=state["summary"],
            findings=state["findings"],
            route=state["route"],
            features=state["features"],
            model_call=state["usage"],
            retrieved_policies=state["policies"],
            complexity_metrics=state.get("complexity_metrics", []),
            review_harness=state["review_harness"],
            finding_validation=state["finding_validation"],
        )
        return {"result": result}

    def _persist_result(self, state: ReviewWorkflowState) -> JsonDict:
        """[11단계] 최종 결과를 저장소에 저장한다."""
        self.store.save_review(state["result"])
        # __class__.__name__ = 저장소 구현 클래스의 이름(어떤 저장소를 썼는지 기록).
        self._publish("review_persisted", {"storage": self.store.__class__.__name__})
        return {}

    def _publish_comment(self, state: ReviewWorkflowState) -> JsonDict:
        """[12단계] 리뷰 결과를 GitHub PR 댓글/체크로 게시한다."""
        publish_result = self.publisher.publish(state["request"], state["result"])
        self._publish("comment_published", publish_result)
        return {"publish_result": publish_result}

    def _complete_review(self, state: ReviewWorkflowState) -> JsonDict:
        """[13단계] 리뷰 완료 이벤트를 발행하며 마무리한다."""
        result = state["result"]
        self._publish(
            "review_completed",
            {
                "status": result.status,
                "route_name": result.route.name,
                "model_tier": result.route.model_tier,
                "findings_count": len(result.findings),
                "workflow_engine": langgraph_runtime_name(),
            },
        )
        return {}
