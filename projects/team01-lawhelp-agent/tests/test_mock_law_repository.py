"""파트 B mock 저장소 테스트. 파트 A 코드(api, agents)에 의존하지 않는다."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 루트 conftest.py는 파트 담당 파일이 아니므로, 테스트 파일에서 직접 경로를 추가한다.
sys.path.insert(0, str(PROJECT_ROOT))

from app.repositories.mock_law_repository import load_law_qa, search_law_qa  # noqa: E402


def test_load_law_qa_returns_all_documents_with_required_fields():
    documents = load_law_qa()
    assert len(documents) == 20
    for document in documents:
        assert document.id
        assert document.question
        assert document.answer
        assert document.category in ("임대차", "근로", "복지")


def test_search_normal_question_returns_matching_documents():
    results = search_law_qa("월세 계약 전에 뭘 확인해야 하나요?")
    assert len(results) >= 1
    assert any(document.id.startswith("rent_") for document in results)


def test_search_no_result_returns_empty_list_without_error():
    results = search_law_qa("상속 포기 절차가 궁금해요")
    assert results == []


def test_search_top_k_limits_result_count():
    results = search_law_qa("월세 계약 전에 뭘 확인해야 하나요?", top_k=1)
    assert len(results) <= 1


def test_test_questions_file_has_all_categories():
    path = PROJECT_ROOT / "data" / "test_questions.json"
    with path.open(encoding="utf-8") as f:
        questions = json.load(f)

    assert set(questions) == {"normal", "should_block", "should_pass", "no_result"}
    assert len(questions["normal"]) >= 3
    assert len(questions["should_block"]) == 3
    assert len(questions["should_pass"]) >= 3
    assert len(questions["no_result"]) >= 1

    all_questions = [q for category in questions.values() for q in category]
    assert len(all_questions) == len(set(all_questions)), "카테고리 간 중복 질문 금지"
