"""
실행 방법은 main함수 참조

RAGAS로 완료된 문의(inquiries)의 AI 답변 품질을 평가하는 스크립트.

기존 앱의 클라이언트 코드를 그대로 재사용한다:
- app.clients.supabase  -> inquiries 테이블 REST 조회
- app.clients.llm       -> LiteLLM 프록시 (평가용 LLM으로 재사용)
- app.clients.http      -> env(), read_json() 등 공통 유틸

전제
- final_answer가 존재하는(=사람이 승인/수정 완료한) 문의만 평가 대상으로 삼는다.
- final_answer를 정답(reference)으로, ai_answer를 평가 대상(response)으로 사용한다.
  -> "AI가 처음 낸 답이 사람이 최종 승인한 답과 얼마나 가까운가"를 측정하는 구조.
- retrieved_docs(jsonb, documents 테이블 검색 결과)를 RAGAS의 retrieved_contexts로 사용한다.

이 파일은 app 패키지 루트에서 실행하는 것을 가정한다 (예: project_root/scripts/evaluate_ragas.py).
개발자용 기능이라고 가정하고 만든 파일이며, python scripts/evaluate_ragas.py --sample-per-category 30 명령어로 직접 실행한다.

설치 필요 패키지
    uv add ragas langchain-openai python-dotenv pandas
    (주의: ragas의 새 llm_factory/embedding_factory 방식은 이 스크립트가 쓰는
     legacy 지표들과 아직 호환되지 않아 langchain 래퍼 방식을 유지한다. 자세한
     이유는 build_ragas_llm() 위 주석 참고.)

필요 환경변수 (기존 앱과 동일)
    SUPABASE_URL, SUPABASE_KEY
    LITELLM_BASE_URL, LITELLM_MASTER_KEY, LITELLM_CHAT_MODEL   (평가용 LLM)
    UPSTAGE_BASE_URL, UPSTAGE_API_KEY,
    UPSTAGE_EMBEDDING_QUERY_MODEL, UPSTAGE_EMBEDDING_PASSAGE_MODEL   (평가용 임베딩)

사용 예시
    python evaluate_ragas.py --sample-per-category 30
    python evaluate_ragas.py --limit 100
    python evaluate_ragas.py --category 긴급 --output urgent_result.csv
"""

import argparse
import importlib
import json
import logging
import os
import sys
import types
import urllib.request
from pathlib import Path
from typing import Any, Optional

# ragas가 내부적으로 GitPython을 import하는데(실험 버전 관리 기능용), git 실행 파일이
# 없는 슬림 컨테이너에서는 import 시점에 에러가 난다. 이 프로젝트는 그 기능을 쓰지 않으므로
# 경고만 띄우고 넘어가도록 설정한다. ragas를 import하기 전에 설정되어 있어야 한다.
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

# -------------------------클로드의 참고 주석--------------------------------
# 아래 두 가지는 "코드"이지 import가 아니지만, 그 아래 import들이 정상 동작하려면
# 반드시 이 두 가지가 먼저 실행되어 있어야 한다:
#
# 1) sys.path에 프로젝트 루트 추가
#    -> 이 스크립트를 scripts/ 폴더에서 실행하든 프로젝트 루트에서 실행하든
#       `app` 패키지를 항상 찾을 수 있게 한다.
# 2) langchain_community.chat_models.vertexai 더미 모듈 등록
#    -> ragas가 (실제로 쓰지도 않는) 이 경로를 내부적으로 import하는데, 최신
#       langchain-community에는 그 경로가 삭제되어 ModuleNotFoundError가 난다
#       (ragas의 알려진 버그: https://github.com/vibrantlabsai/ragas/issues/2745).
#       Vertex AI를 쓰지 않으므로 더미로 채워서 import만 통과시킨다.
#
# 이 두 가지 때문에 아래 import 블록 전체가 파일 최상단에 있지 못하고 ruff(E402)에
# 걸린다. 억지로 최상단으로 올리면 실행 순서가 깨져서 도로 에러가 나므로,
# 이 블록의 import들에는 의도적으로 noqa: E402를 달아둔다.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    importlib.import_module("langchain_community.chat_models.vertexai")
except ModuleNotFoundError:
    _vertexai_stub = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:  # 실제로 호출되지 않는 더미 클래스
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "ChatVertexAI는 더미 스텁입니다. 이 프로젝트는 Vertex AI를 사용하지 않습니다."
            )

    _vertexai_stub.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = _vertexai_stub

from dotenv import load_dotenv  # noqa: E402
from langchain_core.embeddings import Embeddings as LangchainEmbeddingsBase  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from ragas import EvaluationDataset, SingleTurnSample, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_correctness,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from app.clients.embedding import embed as upstage_embed  # noqa: E402
from app.clients.http import env, read_json  # noqa: E402
from app.clients.llm import litellm_base_url  # noqa: E402
from app.clients.supabase import inquiries_table, supabase_headers, supabase_url  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Supabase REST로 완료된 문의 가져오기
# ---------------------------------------------------------------------------
def fetch_completed_inquiries(
    limit: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = "답변 완료",
) -> list[dict[str, Any]]:
    """
    final_answer가 있는(완료된) 문의를 Supabase REST로 가져온다.

    - limit: 최신순 N건만
    - category: 특정 카테고리만
    - status: 완료 상태값. update_final_answer()의 기본값인 "답변 완료"를 기본으로 쓴다.
              None을 주면 상태값 상관없이 final_answer 존재 여부만으로 필터링한다.
    """
    query: dict[str, str] = {
        "select": "*",
        "final_answer": "not.is.null",
        "order": "created_at.desc",
    }
    # eq는 equal의 약자. supabase에서는 ==를 이렇게 씀
    if status:
        query["status"] = f"eq.{status}"
    if category:
        query["categories"] = f"eq.{category}"
    if limit:
        query["limit"] = str(limit)

    request = urllib.request.Request(
        supabase_url(inquiries_table(), query),
        headers=supabase_headers(),
        method="GET",
    )
    rows = read_json(request) or []
    logger.info("완료된 문의 조회: %d건", len(rows))
    return rows


def sample_per_category(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """
    카테고리별로 최신 n건씩 샘플링한다.
    rows는 fetch_completed_inquiries()가 이미 created_at desc로 정렬해 반환한 상태를 가정.
    """
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get("categories"), []).append(row)

    sampled: list[dict[str, Any]] = []
    for _, items in grouped.items():
        sampled.extend(items[:n])
    return sampled


# ---------------------------------------------------------------------------
# 2. retrieved_docs -> RAGAS context 리스트로 변환
# ---------------------------------------------------------------------------
def parse_contexts(retrieved_docs: Any) -> list[str]:
    """
    parse_contexts: 가져온 RAG문서를 파싱한다.
    """
    if retrieved_docs is None:
        return []
    if isinstance(retrieved_docs, str):
        try:
            retrieved_docs = json.loads(retrieved_docs)
        except json.JSONDecodeError:
            return [retrieved_docs]

    contexts: list[str] = []
    if isinstance(retrieved_docs, list):
        for item in retrieved_docs:
            if isinstance(item, dict):
                text = item.get("content") or item.get("text") or item.get("page_content")
                contexts.append(text if text else json.dumps(item, ensure_ascii=False))
            elif isinstance(item, str):
                contexts.append(item)
    elif isinstance(retrieved_docs, dict):
        text = retrieved_docs.get("content") or retrieved_docs.get("text")
        contexts.append(text if text else json.dumps(retrieved_docs, ensure_ascii=False))
    return contexts


# ---------------------------------------------------------------------------
# 3. RAGAS 데이터셋 구성
# ---------------------------------------------------------------------------
def build_ragas_dataset(
    rows: list[dict[str, Any]],
) -> tuple[EvaluationDataset, list[dict[str, Any]]]:
    """
    ai_answer -> response, final_answer -> reference로 매핑.
    context가 없거나 ai_answer/final_answer가 비어있는 건은 평가에서 제외하고,
    실제로 채택된 원본 행들을 함께 반환해서 이후 결과와 매칭할 수 있게 한다.
    """
    samples = []
    kept_rows = []

    for row in rows:
        contexts = parse_contexts(row.get("retrieved_docs"))
        ai_answer = row.get("ai_answer")
        final_answer = row.get("final_answer")
        if not contexts or not ai_answer or not final_answer:
            continue

        samples.append(
            SingleTurnSample(
                user_input=row.get("question") or "",
                response=ai_answer,
                retrieved_contexts=contexts,
                reference=final_answer,
            )
        )
        kept_rows.append(row)

    return EvaluationDataset(samples=samples), kept_rows


# ---------------------------------------------------------------------------
# 4. 평가용 LLM / 임베딩 (기존 인프라 재사용)
#
# 참고: ragas의 새 llm_factory/embedding_factory 방식으로 바꿔봤으나, 아직
# faithfulness/answer_relevancy/context_precision/context_recall/answer_correctness
# 등 여기서 쓰는 지표들은 새 인터페이스(agenerate_prompt 없는 InstructorLLM)와
# 호환되지 않아 전부 실패했다 (AttributeError: 'InstructorLLM' object has no
# attribute 'agenerate_prompt'). ragas가 아직 마이그레이션 중이라 생기는
# 과도기적 불일치라, 지금은 deprecated 되었지만 실제로 동작하는
# LangchainLLMWrapper/LangchainEmbeddingsWrapper 방식을 계속 사용한다.
# 나중에 ragas가 이 지표들도 새 인터페이스로 옮기면 그때 다시 전환을 검토할 것.
# ---------------------------------------------------------------------------
def build_ragas_llm() -> LangchainLLMWrapper:
    """LiteLLM 프록시를 RAGAS 평가용 LLM으로 재사용한다."""
    llm = ChatOpenAI(
        model=env("LITELLM_CHAT_MODEL"),
        base_url=litellm_base_url(),
        api_key=env("LITELLM_MASTER_KEY"),
        temperature=0,  # 값이 높을수록 창의성 높은 답이 나옴
    )
    return LangchainLLMWrapper(llm)


class _UpstageLangchainEmbeddings(LangchainEmbeddingsBase):
    """
    langchain의 Embeddings 인터페이스(embed_documents/embed_query)를 구현하되,
    실제 호출은 app.clients.embedding.embed()를 그대로 사용한다.

    langchain의 OpenAIEmbeddings를 썼을 때는 배치 크기(chunk_size)를 1로 줄여도
    여전히 {"input": ["텍스트"]}처럼 리스트 형태로 요청을 보내서 Upstage API가
    "'$.input' is invalid"로 거부했다. Upstage는 리스트 자체를 받지 않고
    {"input": "텍스트"}처럼 순수 문자열만 받기 때문이다 (embed() 함수가 원래
    그렇게 구현되어 있음). 그래서 배치 없이 한 번에 하나씩, embed()를 그대로
    호출하는 이 래퍼를 쓴다.

    즉 UpstageAPI를 쓰려면 필수적인 과정이다
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [upstage_embed(text, kind="passage") for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return upstage_embed(text, kind="query")


def build_ragas_embeddings() -> LangchainEmbeddingsWrapper:
    """Upstage 임베딩을 기존 app.clients.embedding.embed() 그대로 재사용한다."""
    return LangchainEmbeddingsWrapper(_UpstageLangchainEmbeddings())


# 평가 지표들 설정
# 자세한 공식이나 자료는 공식 문서 참조: https://docs.ragas.io/en/v0.3.9/concepts/metrics/available_metrics/
# 여기서는 아래 5가지 지표로 평가한다
def run_evaluation(dataset: EvaluationDataset):
    metrics = [
        faithfulness,  # 답변이 검색된 문서에 근거하는지 (환각 여부)
        # answer_relevancy,  # 답변이 질문과 얼마나 관련 있는지(현재 LLM모델과 연관된 버그 있어서 비활성화)
        context_precision,  # 검색된 문서 중 실제 정답 생성에 유용했던 비율
        context_recall,  # 정답 생성에 필요한 정보를 검색이 충분히 커버했는지
        answer_correctness,  # ai_answer가 final_answer와 얼마나 일치하는지 (핵심 지표)
    ]
    return evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=build_ragas_llm(),
        embeddings=build_ragas_embeddings(),
    )


# ---------------------------------------------------------------------------
# main
# 실행 예시: python scripts/evaluate_ragas.py --sample-per-category 30
# --sample-per-category: 카테고리별 층화 샘플링 건수. 각 카테고리마다 최신순으로 지정한 숫자만큼만 뽑아서 검사합니다. (예: 30을 주면 카테고리별로 30건씩만 평가)
# --limit: 전체 데이터 제한 건수. 카테고리 상관없이 무조건 최신순으로 딱 N건만 가져와서 평가합니다.
# --category: 특정 카테고리 지정. 데이터베이스에서 특정 카테고리(예: '긴급', '일반')에 해당하는 문의만 필터링해서 평가합니다.
# --status: 문의의 상태값 필터. 기본적으로 '답변 완료' 상태인 데이터만 평가하며, 상태와 상관없이 final_answer가 있는 모든 데이터를 보려면 빈 문자열("")을 주면 됩니다.
# ---------------------------------------------------------------------------
def main():
    load_dotenv(_PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="완료된 문의에 대해 RAGAS 평가 실행")
    parser.add_argument("--limit", type=int, default=None, help="최신순 N건만 평가")
    parser.add_argument("--category", type=str, default=None, help="특정 카테고리만 평가")
    parser.add_argument(
        "--sample-per-category",
        type=int,
        default=None,
        help="카테고리별 층화 샘플링 건수 (예: 30 -> 카테고리마다 최신 30건)",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="답변 완료",
        help="완료 상태값 (기본: '답변 완료'). 상태 무관하게 보려면 빈 문자열('') 지정",
    )
    parser.add_argument("--output", type=str, default="ragas_result.csv")
    args = parser.parse_args()

    rows = fetch_completed_inquiries(
        limit=args.limit,
        category=args.category,
        status=args.status or None,
    )
    if args.sample_per_category:
        rows = sample_per_category(rows, args.sample_per_category)

    print(f"평가 대상 문의 수: {len(rows)}건")

    dataset, kept_rows = build_ragas_dataset(rows)
    print(f"context 존재하여 실제 평가 가능한 건수: {len(dataset)}건")

    if len(dataset) == 0:
        print("평가할 데이터가 없습니다. retrieved_docs 형식을 확인해주세요.")
        return

    result = run_evaluation(dataset)
    result_df = result.to_pandas()

    result_df["inquiry_id"] = [r.get("inquiry_id") for r in kept_rows]
    result_df["categories"] = [r.get("categories") for r in kept_rows]
    result_df["created_at"] = [r.get("created_at") for r in kept_rows]
    result_df["reviewer_type"] = [r.get("reviewer_type") for r in kept_rows]

    result_df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"\n결과 저장: {args.output}")

    metric_cols = [
        "faithfulness",
        # "answer_relevancy", (현재 특정 LLM관련 버그 있음. 임시 비활성화)
        "context_precision",
        "context_recall",
        "answer_correctness",
    ]
    print("\n=== 전체 평균 ===")
    print(result_df[metric_cols].mean())
    print("\n=== 카테고리별 평균 ===")
    print(result_df.groupby("categories")[metric_cols].mean())


if __name__ == "__main__":
    main()
