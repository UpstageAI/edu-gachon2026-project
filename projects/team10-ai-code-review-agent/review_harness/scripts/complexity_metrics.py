"""순환 복잡도(cyclomatic complexity) 측정기: 심층 리뷰에서만 쓰는 정량 지표.

순환 복잡도는 "함수 안에 분기(if/for/while 등)가 얼마나 많은가"를 나타내는 수치로,
높을수록 이해·테스트가 어렵다. Radon 라이브러리로 파이썬 함수별 값을 재고,
변경 전(base)과 후(head)를 비교해 이 PR이 복잡도를 얼마나 바꿨는지 ComplexityMetric에
담는다. 모델이 복잡도를 추측하지 않고 실제 수치를 근거로 삼게 하는 것이 목적이다.
"""

from __future__ import annotations

from collections.abc import Iterable

# radon: 파이썬 코드 복잡도 분석 라이브러리.
# cc_visit = 소스에서 함수별 복잡도를 잰다. cc_rank = 복잡도 수치를 A~F 등급으로 바꾼다.
from radon.complexity import cc_rank, cc_visit

from backend.app.core.schemas import ChangedFilePayload, ComplexityMetric, ReviewRequest

# 이 값을 넘는 함수는 "복잡도 과다"로 표시한다(경험적 임계값).
PYTHON_CYCLOMATIC_COMPLEXITY_THRESHOLD = 15
# 너무 큰 파일은 분석하지 않는다(성능 보호). 200_000의 밑줄은 자릿수 구분용 표기다.
MAX_SOURCE_CHARS = 200_000


def _python_functions(source: str) -> dict[str, tuple[int, int]]:
    """파이썬 소스에서 {함수이름: (복잡도, 시작줄)} 사전을 만든다.

    빈 소스/과대 파일이거나 문법 오류로 분석에 실패하면 빈 사전을 돌려준다(방어적).
    tuple(int, int)은 값 두 개를 묶은 불변 쌍이다.
    """
    if not source or len(source) > MAX_SOURCE_CHARS:
        return {}
    try:
        blocks = cc_visit(source)
    except (SyntaxError, TypeError, ValueError):
        # 미완성/깨진 코드도 있을 수 있어 예외를 잡고 조용히 넘어간다.
        return {}
    # 딕셔너리 컴프리헨션으로 함수 블록만 골라 사전을 만든다.
    # getattr(block, "fullname", block.name): fullname이 있으면 그것(중첩 함수까지
    # 포함한 전체 이름), 없으면 name을 쓴다. 클래스 메서드 등도 이름으로 구분하려는 것.
    return {
        str(getattr(block, "fullname", block.name)): (block.complexity, block.lineno)
        for block in blocks
        if block.__class__.__name__ == "Function"
    }


def analyze_python_file(
    changed_file: ChangedFilePayload,
    threshold: int = PYTHON_CYCLOMATIC_COMPLEXITY_THRESHOLD,
) -> list[ComplexityMetric]:
    """파일 하나의 변경 전/후 복잡도를 함수별로 비교해 변화가 있는 것만 기록한다."""
    before_functions = _python_functions(changed_file.base_content)
    after_functions = _python_functions(changed_file.head_content)
    metrics: list[ComplexityMetric] = []
    # sorted(...items())로 함수 이름순 정렬해 결과 순서를 항상 일정하게 한다.
    # for ... (after, line_start): 튜플을 두 변수로 한 번에 풀어 받는 언팩.
    for symbol, (after, line_start) in sorted(after_functions.items()):
        # 변경 전에 없던 함수면 기본값 (0, 0)에서 [0]으로 복잡도 0을 꺼낸다.
        before = before_functions.get(symbol, (0, 0))[0]
        if after == before:
            continue  # 복잡도가 그대로면 보고할 게 없다.
        metrics.append(
            ComplexityMetric(
                metric_id=(
                    f"python:cyclomatic_complexity:{changed_file.path}:{symbol}"
                ),
                tool="radon",
                metric="cyclomatic_complexity",
                file_path=changed_file.path,
                symbol=symbol,
                line_start=line_start,
                before=before,
                after=after,
                delta=after - before,  # 양수면 이 PR이 복잡도를 올렸다는 뜻.
                threshold=threshold,
                exceeded_threshold=after > threshold,
                # cc_rank는 0을 못 받으므로 max(1, ...)로 최소 1을 보장한다.
                rank_before=cc_rank(max(1, before)),
                rank_after=cc_rank(max(1, after)),
            )
        )
    return metrics


def analyze_complexity(
    request: ReviewRequest,
    threshold: int = PYTHON_CYCLOMATIC_COMPLEXITY_THRESHOLD,
) -> list[ComplexityMetric]:
    """PR 전체의 복잡도 지표를 모은다. 심층 리뷰가 아니면 계산하지 않고 건너뛴다."""
    if request.review_mode != "deep_quality_review":
        return []
    metrics: list[ComplexityMetric] = []
    # 제너레이터 표현식: 조건에 맞는 파이썬 파일만 그때그때 하나씩 걸러 낸다
    # (리스트를 미리 다 만들지 않아 메모리에 유리하다).
    python_files: Iterable[ChangedFilePayload] = (
        changed_file
        for changed_file in request.changed_files
        if changed_file.path.lower().endswith(".py") and changed_file.head_content
    )
    for changed_file in python_files:
        metrics.extend(analyze_python_file(changed_file, threshold=threshold))
    return metrics
