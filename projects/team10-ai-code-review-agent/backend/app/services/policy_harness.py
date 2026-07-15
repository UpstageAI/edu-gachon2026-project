"""리뷰 하네스: diff 신호를 보고 어떤 검토 절차/근거를 쓸지 고르는 단계.

diff_signals.py가 뽑은 신호(security, api_contract 등)를 입력으로 받아, 이 PR에 맞는
skill(검토 절차)과 knowledge card(검토 관점 근거), 참고할 정책 유형(policy_type)을
선택한다. 이 결과(ReviewHarnessContext)가 모델 프롬프트에 들어가 리뷰 품질을 좌우한다.

구성:
- manifest.json : 어떤 skill들이 있고, 어떤 route/신호일 때 켜지는지 정의한 설정 파일.
- sources / knowledge cards : skill이 인용할 수 있는 공식 출처와 검토 관점 카드.
- __init__에서 이 설정들을 읽고 무결성을 검증한다(잘못되면 즉시 에러로 알림).
- select()가 실제 선택 로직으로, 점수를 매겨 상위 몇 개의 skill/카드를 고른다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.core.schemas import (
    ReviewHarnessContext,
    ReviewKnowledgeCard,
    ReviewRequest,
    ReviewRoute,
    ReviewSkill,
    ReviewSourceReference,
)
from review_harness.scripts.diff_signals import analyze_diff, reviewable_patch_text


class PolicyHarness:
    """하네스 설정을 읽어 두고, 요청마다 알맞은 skill/카드를 골라 주는 객체."""

    def __init__(self, root: Path) -> None:
        # root: 하네스 리소스(manifest.json 등)가 들어 있는 폴더.
        # 생성 시점에 모든 설정을 읽고 검증까지 끝내, 이후 select()는 빠르게 동작한다.
        self.root = root
        self.manifest = self._load_manifest()
        self.source_ids = self._load_source_ids()
        self.design_source_ids = self._load_design_source_ids()
        self._validate_skills()
        self.knowledge_cards = self._load_knowledge_cards()

    def _load_manifest(self) -> dict[str, Any]:
        """manifest.json을 읽어 사전으로 돌려준다. 형식이 잘못되면 에러를 낸다.

        / 연산자는 Path에서 "경로 잇기"를 뜻한다(root / "manifest.json").
        isinstance(x, dict)는 x가 사전 타입인지 확인하는 함수다.
        """
        manifest_path = self.root / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"review harness manifest is missing: {manifest_path}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
            raise RuntimeError("review harness manifest must contain a skills list")
        return payload

    def _skill_instructions(self, relative_path: str) -> str:
        """skill 문서(SKILL.md 등)의 지침 텍스트를 읽어 온다(최대 2400자).

        보안상 중요: resolve()로 실제 경로를 구한 뒤, 그 경로가 root 하위에 있는지
        검사해 하네스 폴더 바깥 파일을 읽지 못하게 막는다(경로 탈출 방지).
        """
        root = self.root.resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"invalid review skill path: {relative_path}")
        return path.read_text(encoding="utf-8").strip()[:2400]

    def _reference_payload(self, manifest_key: str) -> dict[str, Any]:
        """manifest가 가리키는 참조 JSON 파일(sources/cards 등)을 안전하게 읽어 온다."""
        relative_path = str(self.manifest.get(manifest_key) or "")
        root = self.root.resolve()
        path = (root / relative_path).resolve()
        # 경로가 비었거나 root 밖이거나 파일이 아니면 거부(위와 같은 경로 탈출 방지).
        if not relative_path or root not in path.parents or not path.is_file():
            raise RuntimeError(f"invalid review harness reference: {relative_path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"review harness reference must be an object: {relative_path}")
        return payload

    def _load_source_ids(self) -> set[str]:
        """공식 출처 목록을 읽어 유효성을 검사하고, 출처 ID들의 집합을 돌려준다.

        각 출처는 id/authority/title이 있어야 하고 URL은 https여야 하며 ID는 중복 불가.
        이렇게 미리 검증해 두면, skill/카드가 존재하지 않는 출처를 인용하는 것을 막는다.

        동시에 id → {title, url, authority} 사전(self._source_records)도 채워 둔다.
        skill/카드는 source_ids(문자열 ID)만 들고 있어, 리뷰 결과에 "이 카드는 어떤
        문서를 근거로 삼았는지" 사람이 읽을 제목·링크로 보여 주려면 이 사전이 필요하다
        (select()에서 _source_references()로 다시 찾아 쓴다).
        """
        payload = self._reference_payload("sources_path")
        sources = payload.get("sources")
        if not isinstance(sources, list):
            raise RuntimeError("review harness sources must contain a sources list")
        source_ids: set[str] = set()
        records: dict[str, dict[str, str]] = {}
        for source in sources:
            if not isinstance(source, dict):
                raise RuntimeError("review harness source must be an object")
            # str(x or "") : x가 없거나(None) 비면 빈 문자열로 안전하게 만든다.
            source_id = str(source.get("id") or "")
            url = str(source.get("url") or "")
            authority = str(source.get("authority") or "")
            title = str(source.get("title") or "")
            if not source_id or not authority or not title:
                raise RuntimeError("review harness source requires id, authority, and title")
            if not url.startswith("https://"):
                raise RuntimeError(f"review harness source must use HTTPS: {source_id}")
            if source_id in source_ids:
                raise RuntimeError(f"duplicate review harness source ID: {source_id}")
            source_ids.add(source_id)
            records[source_id] = {"title": title, "url": url, "authority": authority}
        self._source_records = records
        return source_ids

    def _source_references(self, source_ids: list[str]) -> list[ReviewSourceReference]:
        """출처 ID 목록을 리뷰 댓글에 그대로 보여 줄 수 있는 제목/링크 목록으로 바꾼다."""
        return [
            ReviewSourceReference(
                source_id=source_id,
                title=self._source_records.get(source_id, {}).get("title", source_id),
                url=self._source_records.get(source_id, {}).get("url", ""),
                authority=self._source_records.get(source_id, {}).get("authority", ""),
            )
            for source_id in source_ids
        ]

    def _validate_skills(self) -> None:
        """manifest의 skill들을 검증한다. ID 중복, 출처 누락/미등록, 문서 경로를 확인."""
        skill_ids: set[str] = set()
        for item in self.manifest["skills"]:
            if not isinstance(item, dict):
                raise RuntimeError("review harness skill must be an object")
            skill_id = str(item.get("id") or "")
            # 집합 컴프리헨션 {..}: skill이 참조하는 출처 ID들을 중복 없이 모은다.
            source_ids = {str(value) for value in item.get("source_ids", [])}
            if not skill_id or skill_id in skill_ids:
                raise RuntimeError(f"invalid or duplicate review harness skill ID: {skill_id}")
            if not source_ids:
                raise RuntimeError(f"review harness skill requires source IDs: {skill_id}")
            # - 는 차집합: skill이 쓰는 출처 중 등록되지 않은(알 수 없는) 것만 남긴다.
            unknown_sources = source_ids - self.source_ids
            if unknown_sources:
                raise RuntimeError(
                    f"unknown review harness source IDs for {skill_id}: "
                    f"{sorted(unknown_sources)}"
                )
            self._skill_instructions(str(item.get("path") or ""))  # 문서가 실제로 읽히는지도 확인.
            skill_ids.add(skill_id)

    def _load_design_source_ids(self) -> set[str]:
        """UI/디자인 관련 출처 ID 집합을 읽고, 등록된 출처인지 검증한다."""
        source_ids = {str(value) for value in self.manifest.get("design_source_ids", [])}
        unknown_sources = source_ids - self.source_ids  # 미등록 출처가 있으면 에러.
        if unknown_sources:
            raise RuntimeError(
                f"unknown review harness design source IDs: {sorted(unknown_sources)}"
            )
        return source_ids

    def _load_knowledge_cards(self) -> list[dict[str, Any]]:
        """지식 카드 목록을 읽고 검증한다. 필수 필드/중복 ID/연결된 skill·출처를 확인."""
        payload = self._reference_payload("knowledge_cards_path")
        cards = payload.get("cards")
        if not isinstance(cards, list):
            raise RuntimeError("review harness knowledge cards must contain a cards list")
        # 카드가 가리키는 skill이 실제로 존재하는지 대조하기 위한 skill ID 집합.
        known_skills = {str(item["id"]) for item in self.manifest["skills"]}
        card_ids: set[str] = set()
        # 카드가 반드시 가져야 하는 필드들.
        required_fields = {
            "id",
            "title",
            "skill_id",
            "check",
            "evidence_required",
            "false_positive_guard",
            "severity_cap",
        }
        for card in cards:
            if not isinstance(card, dict):
                raise RuntimeError("review harness knowledge card must be an object")
            # 값이 비어 있는 필수 필드를 리스트로 모은다(리스트 컴프리헨션).
            missing_fields = [field for field in required_fields if not card.get(field)]
            if missing_fields:
                raise RuntimeError(
                    f"review harness knowledge card is incomplete: {sorted(missing_fields)}"
                )
            card_id = str(card["id"])
            if card_id in card_ids:
                raise RuntimeError(f"duplicate review harness knowledge card ID: {card_id}")
            if str(card["skill_id"]) not in known_skills:
                raise RuntimeError(f"unknown skill for review knowledge card: {card_id}")
            source_ids = {str(source_id) for source_id in card.get("source_ids", [])}
            if not source_ids:
                raise RuntimeError(f"review knowledge card requires source IDs: {card_id}")
            unknown_sources = source_ids - self.source_ids  # 미등록 출처 검사.
            if unknown_sources:
                raise RuntimeError(
                    f"unknown review harness source IDs: {sorted(unknown_sources)}"
                )
            card_ids.add(card_id)
        return cards

    # @staticmethod: self(인스턴스)가 필요 없는 순수 도우미 함수. 클래스 안에 두었을 뿐.
    @staticmethod
    def _contains_marker(text: str, marker: str) -> bool:
        """text 안에 marker가 들어 있는지 검사한다. 단, 단어형 마커는 "온전한 단어"로만.

        marker가 소문자/숫자/밑줄로만 된 단어면(예: token) 정규식으로 앞뒤에 다른
        식별자 글자가 없는 경우에만 매칭한다. 이렇게 해야 "token"이 "tokenizer"의
        일부로 잘못 걸리는 오탐을 막는다. 그 외(기호 포함 마커)는 단순 부분 문자열 검사.
        """
        # (?<!...) / (?!...) 는 "앞/뒤에 이런 글자가 오면 안 됨"이라는 정규식 경계 조건.
        # re.escape는 marker 안의 특수문자를 글자 그대로 취급하게 이스케이프한다.
        if re.fullmatch(r"[a-z0-9_]+", marker):
            return re.search(rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])", text) is not None
        return marker in text

    def select(self, request: ReviewRequest, route: ReviewRoute) -> ReviewHarnessContext:
        """이 요청/경로에 맞는 skill과 지식 카드를 골라 ReviewHarnessContext로 돌려준다.

        route: routing.py의 select_route()가 정한 리뷰 경로(어떤 skill이 켜지는지 좌우).
        전체 흐름: 신호 수집 → skill 점수화·선택 → 관련 지식 카드 점수화·선택.
        """
        signals = analyze_diff(request)
        # 복잡도 측정 결과도 신호로 추가한다(diff_signals가 못 만드는 정량 신호).
        measured_metrics = [metric.metric_id for metric in request.complexity_metrics]
        # 임계값을 넘고(delta>0) 복잡도가 늘어난 것만 "회귀(regression)" 신호로.
        complexity_regressions = [
            metric.metric_id
            for metric in request.complexity_metrics
            if metric.exceeded_threshold and metric.delta > 0
        ]
        if measured_metrics:
            signals["complexity_measured"] = measured_metrics
        if complexity_regressions:
            signals["complexity_regression"] = complexity_regressions
        selected: list[ReviewSkill] = []
        for item in self.manifest["skills"]:
            # 이 skill이 켜지는 경로 목록. 현재 route가 아니면 건너뛴다.
            routes = {str(value) for value in item.get("routes", [])}
            if route.name not in routes:
                continue
            required_signals = {str(value) for value in item.get("signals", [])}
            # & 는 교집합: 이 skill이 요구하는 신호 중 실제로 감지된 것들.
            # signals.keys()는 감지된 신호 이름들이다.
            matched_signals = required_signals & signals.keys()
            always_routes = {str(value) for value in item.get("always_routes", [])}
            # always면 신호가 없어도 항상 포함되는 skill(예: 기본 검토 절차).
            always_for_route = bool(item.get("always", False)) or route.name in always_routes
            if not always_for_route and not matched_signals:
                continue
            # 점수 공식: 항상 켜지는 skill에 +100(최우선), manifest의 우선순위 가산,
            # 감지된 신호 하나당 +20. 아래에서 이 점수로 정렬해 상위만 남긴다.
            score = (
                (100 if always_for_route else 0)
                + int(item.get("priority", 0))
                + (20 * len(matched_signals))
            )
            skill_source_ids = [str(value) for value in item.get("source_ids", [])]
            selected.append(
                ReviewSkill(
                    skill_id=str(item["id"]),
                    title=str(item.get("title") or item["id"]),
                    instructions=self._skill_instructions(str(item["path"])),
                    policy_types=[str(value) for value in item.get("policy_types", [])],
                    source_ids=skill_source_ids,
                    sources=self._source_references(skill_source_ids),
                    score=score,
                )
            )

        # 경로별로 몇 개의 skill까지 쓸지 상한(없으면 3개).
        limits = self.manifest.get("max_skills", {})
        max_skills = int(limits.get(route.name, 3))
        # 점수 높은 순으로 정렬. 튜플 (-점수, id) 로 "점수 내림차순, 동점이면 id 오름차순".
        ranked = sorted(selected, key=lambda skill: (-skill.score, skill.skill_id))
        # 후보 전체가 다루는 정책 유형(잘려나가기 전 기준). 중첩 for로 모아 중복 제거·정렬.
        candidate_policy_types = sorted(
            {policy_type for skill in ranked for policy_type in skill.policy_types}
        )
        selected = ranked[:max_skills]  # 상위 max_skills개만 실제 채택.
        # 최종 채택된 skill들이 다루는 정책 유형(RAG 검색을 이 유형들로 좁히는 데 쓰임).
        policy_types = sorted(
            {policy_type for skill in selected for policy_type in skill.policy_types}
        )
        selected_skill_ids = {skill.skill_id for skill in selected}
        # 파일별 (경로, 검토용 patch 텍스트) 쌍을 미리 소문자로 만들어 둔다(마커 매칭용).
        changed_file_signals = [
            (file.path.lower(), reviewable_patch_text(file.patch).lower())
            for file in request.changed_files
        ]
        # _ 는 "안 쓰는 값"을 받을 때 관례적으로 쓰는 변수 이름이다.
        changed_paths = "\n".join(path for path, _ in changed_file_signals)
        changed_patches = "\n".join(patch for _, patch in changed_file_signals)
        cards: list[ReviewKnowledgeCard] = []
        for item in self.knowledge_cards:
            # 카드는 채택된 skill에 속한 것만 후보로 본다.
            skill_id = str(item.get("skill_id") or "")
            if skill_id not in selected_skill_ids:
                continue
            routes = {str(value) for value in item.get("routes", [])}
            if routes and route.name not in routes:
                continue
            required_signals = {str(value) for value in item.get("signals", [])}
            matched_signals = required_signals & signals.keys()
            always = bool(item.get("always", False))
            # 신호를 요구하는데 하나도 안 맞고 always도 아니면 제외.
            if required_signals and not matched_signals and not always:
                continue
            # 이 카드가 찾을 경로/patch 마커들(소문자).
            path_markers = [str(value).lower() for value in item.get("path_markers", [])]
            patch_markers = [str(value).lower() for value in item.get("patch_markers", [])]
            # next((...), None): 조건에 맞는 첫 마커, 없으면 None. 어떤 마커가 걸렸는지 기록.
            matched_path = next(
                (
                    marker
                    for marker in path_markers
                    if self._contains_marker(changed_paths, marker)
                ),
                None,
            )
            matched_patch = next(
                (
                    marker
                    for marker in patch_markers
                    if self._contains_marker(changed_patches, marker)
                ),
                None,
            )
            # 경로 마커와 patch 마커가 "같은 파일 하나"에서 동시에 걸리는지 찾는다.
            # 중첩 for로 (파일 × 경로마커 × patch마커) 조합을 훑어 첫 성립 쌍을 얻는다.
            matched_same_file = next(
                (
                    (path_marker, patch_marker)
                    for path, patch in changed_file_signals
                    for path_marker in path_markers
                    for patch_marker in patch_markers
                    if self._contains_marker(path, path_marker)
                    and self._contains_marker(patch, patch_marker)
                ),
                None,
            )
            # require_patch: patch 쪽 증거가 없으면 이 카드는 쓰지 않는다.
            if item.get("require_patch") and not matched_patch:
                continue
            # require_path_and_patch: 경로와 patch가 같은 파일에서 함께 걸려야만 인정.
            if item.get("require_path_and_patch"):
                if not matched_same_file:
                    continue
                matched_path, matched_patch = matched_same_file
            # 마커 조건이 있는데 아무것도 안 걸리고 always도 아니면 제외.
            if (path_markers or patch_markers) and not (matched_path or matched_patch or always):
                continue
            card_source_ids = [str(value) for value in item.get("source_ids", [])]
            cards.append(
                ReviewKnowledgeCard(
                    card_id=str(item["id"]),
                    title=str(item.get("title") or item["id"]),
                    skill_id=skill_id,
                    check=str(item.get("check") or ""),
                    evidence_required=str(item.get("evidence_required") or ""),
                    false_positive_guard=str(item.get("false_positive_guard") or ""),
                    severity_cap=str(item.get("severity_cap") or "medium"),
                    source_ids=card_source_ids,
                    sources=self._source_references(card_source_ids),
                    forbidden_claim_markers=[
                        str(value).lower()
                        for value in item.get("forbidden_claim_markers", [])
                    ],
                    # 카드 점수: 신호 하나당 +20, 경로/patch 마커가 걸리면 각 +10,
                    # always면 +5. 관련도가 높을수록 점수가 커진다.
                    score=(
                        (20 * len(matched_signals))
                        + (10 if matched_path else 0)
                        + (10 if matched_patch else 0)
                        + (5 if always else 0)
                    ),
                )
            )
        # 경로별 카드 개수 상한(없으면 5개).
        max_cards = int(
            self.manifest.get("max_knowledge_cards", {}).get(route.name, 5)
        )
        ranked_cards = sorted(cards, key=lambda card: (-card.score, card.card_id))
        selected_cards: list[ReviewKnowledgeCard] = []
        selected_card_ids: set[str] = set()
        # 1단계: 채택된 각 skill마다 그 skill의 최고 점수 카드를 하나씩 우선 확보한다
        # (모든 skill이 최소한 한 장의 근거 카드를 갖도록 공정하게 분배).
        for skill in selected:
            best_for_skill = next(
                (card for card in ranked_cards if card.skill_id == skill.skill_id),
                None,
            )
            if best_for_skill is None or best_for_skill.card_id in selected_card_ids:
                continue
            selected_cards.append(best_for_skill)
            selected_card_ids.add(best_for_skill.card_id)
            if len(selected_cards) >= max_cards:
                break
        # 2단계: 남은 자리를 점수 높은 카드로 마저 채운다(이미 뽑힌 것은 건너뜀).
        for card in ranked_cards:
            if len(selected_cards) >= max_cards:
                break
            if card.card_id in selected_card_ids:
                continue
            selected_cards.append(card)
            selected_card_ids.add(card.card_id)
        return ReviewHarnessContext(
            version=str(self.manifest.get("version", "1")),
            signals=signals,
            skills=selected,
            knowledge_cards=selected_cards,
            policy_types=policy_types,
            candidate_policy_types=candidate_policy_types,
        )

    # @property: 괄호 없이 harness.max_policies_per_batch 처럼 값처럼 읽는 속성.
    @property
    def max_policies_per_batch(self) -> int:
        """한 번의 모델 배치에 넣을 정책 조각 최대 개수(최소 1은 보장)."""
        return max(1, int(self.manifest.get("max_policies_per_batch", 2)))
