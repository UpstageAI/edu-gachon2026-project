"""GitHub App 연동 계층: GitHub와 실제로 통신하는 부분을 모아 둔 파일.

리뷰 파이프라인의 "입구(webhook 수신)"와 "GitHub API 호출"을 담당한다.
- verify_github_signature() : GitHub가 보낸 webhook이 진짜인지 서명으로 검증.
- GitHubAppClient           : App 인증(JWT→installation token)과 GitHub REST API
  호출(PR/파일/체크 조회, 파일 내용 읽기, check run 생성/갱신) 도우미.
- GitHubWebhookProcessor    : 받은 webhook 이벤트를 해석해, 리뷰할지/무시할지 그리고
  어떤 ReviewRequest들을 만들지 정하는 "review_plan"을 돌려준다.

이벤트별로 다르게 분기한다: pull_request 열림/갱신, 체크(check_suite/check_run) 완료,
그리고 사용자가 "심층 리뷰 실행" 버튼을 눌렀을 때(requested_action)다. 심층 리뷰일
때는 복잡도 측정을 위해 파이썬 원본 파일 내용까지 추가로 붙인다.

외부 HTTP 라이브러리 없이 표준 라이브러리 urllib.request만으로 GitHub API를 호출한다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from backend.app.core.config import Settings
from backend.app.core.schemas import ReviewRequest
from backend.app.services.rag import REPOSITORY_POLICY_PATH, split_policy_markdown

# 사용자가 "심층 리뷰 실행" 버튼을 누르면 GitHub이 이 문자열을 identifier로 보내 온다.
# publisher.py가 버튼을 만들 때도, 여기서 버튼 클릭을 알아볼 때도 같은 값을 쓴다.
DEEP_REVIEW_ACTION_IDENTIFIER = "run_deep_review"


# webhook 처리 중 "요청이 잘못됨"을 알리는 전용 예외. ValueError를 상속해, 이 예외를
# 잡는 쪽에서 일반적인 잘못된 입력과 같은 방식으로 다룰 수 있다.
class GitHubWebhookError(ValueError):
    pass


def verify_github_signature(
    payload_body: bytes,
    secret: str | None,
    signature_header: str | None,
) -> None:
    """받은 webhook이 정말 GitHub이 보낸 것인지 HMAC 서명으로 검증한다.

    GitHub은 우리와 공유한 비밀키(secret)로 본문을 서명해 헤더에 실어 보낸다. 같은
    비밀키로 본문을 다시 서명해 그 값이 일치하는지 본다. 위조된 요청을 막는 관문이다.
    문제가 없으면 아무것도 반환하지 않고, 이상하면 예외를 던진다.
    """
    if not secret:
        raise RuntimeError("GITHUB_WEBHOOK_SECRET is required for GitHub webhook delivery")
    if not signature_header:
        raise GitHubWebhookError("X-Hub-Signature-256 header is required")

    # hmac + sha256으로 본문 서명을 계산한다. GitHub 규약대로 "sha256=" 접두어를 붙인다.
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    # compare_digest: 단순 == 대신 "타이밍 공격"에 안전하게 두 값을 비교한다.
    if not hmac.compare_digest(expected, signature_header):
        raise GitHubWebhookError("GitHub webhook signature mismatch")


def normalize_private_key(raw_value: str) -> str:
    """설정으로 받은 App 개인키를 어떤 형태로 넣었든 표준 PEM 문자열로 정리한다.

    환경변수에 개인키를 넣는 방식이 제각각이라(줄바꿈이 \\n으로 escape되거나, 전체가
    base64로 인코딩되거나) 세 경우를 모두 받아들여 JWT 서명에 쓸 PEM으로 통일한다.
    """
    value = raw_value.strip()
    # 1) 줄바꿈이 문자 그대로 "\n"으로 들어온 경우 진짜 줄바꿈으로 되돌린다.
    candidate = value.replace("\\n", "\n")
    if "PRIVATE KEY" in candidate:
        return candidate.strip() + "\n"

    # 2) 그래도 PEM 헤더가 없으면 전체가 base64로 인코딩됐다고 보고 디코딩을 시도한다.
    # re.sub(r"\s+", "", value): 모든 공백/줄바꿈을 제거해 한 줄로 만든다.
    compact = re.sub(r"\s+", "", value)
    try:
        decoded = base64.b64decode(compact, validate=True).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(
            "GITHUB_APP_PRIVATE_KEY must be a PEM private key, escaped PEM, or base64 PEM"
        ) from exc

    if "PRIVATE KEY" not in decoded:
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY does not contain a private key")
    return decoded.strip() + "\n"


class GitHubAppClient:
    """GitHub App으로 인증하고 GitHub REST API를 호출하는 도우미 모음.

    인증 2단계: create_jwt()로 App 신원을 증명하는 짧은 JWT를 만들고, 그 JWT로
    installation_token()을 불러 특정 설치(저장소)에 쓸 수 있는 실제 API 토큰을 받는다.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_jwt(self) -> str:
        """App 자신을 증명하는 JWT(JSON Web Token)를 만든다. 유효기간은 약 9분.

        JWT는 개인키로 서명한 짧은 신분증이다. GitHub이 공개키로 검증해 "이 App이 맞다"를
        확인한다. 이 JWT 자체로는 저장소를 못 만지고, installation token 발급에만 쓴다.
        """
        # PyJWT(jwt)는 선택 의존성이라, 없을 때 친절한 에러를 낸다.
        try:
            import jwt
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("PyJWT is required for GitHub App authentication") from exc

        if not self.settings.github_app_id:
            raise RuntimeError("GITHUB_APP_ID is required for GitHub App authentication")

        now = int(time.time())
        # iat를 60초 과거로 두는 것은 서버 간 시계 오차로 "미래 발급" 취급되는 것을 막기
        # 위함이다. exp(만료)는 발급 후 540초(9분) 뒤. iss(발급자)는 App ID.
        payload = {
            "iat": now - 60,
            "exp": now + 540,
            "iss": self.settings.github_app_id,
        }
        # RS256: 개인키로 서명하고 공개키로 검증하는 비대칭 서명 알고리즘.
        return jwt.encode(payload, self._private_key(), algorithm="RS256")

    def installation_token(self, installation_id: str | int) -> str:
        """JWT로 특정 설치(installation)에 대한 실제 액세스 토큰을 발급받는다.

        이 토큰이 있어야 해당 저장소의 PR/파일/체크를 읽고 댓글을 달 수 있다. 토큰은
        약 1시간짜리 단기 토큰이라, 발행할 때마다 새로 받아 쓰는 것이 일반적이다.
        """
        payload = self.request_json(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self.create_jwt(),
        )
        token = str(payload.get("token", ""))
        if not token:
            raise RuntimeError("GitHub installation access token response did not include token")
        return token

    def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        token: str,
    ) -> dict[str, Any]:
        # PR 하나의 메타데이터(제목, base/head 커밋 등)를 가져온다.
        return self.request_json(
            "GET",
            f"/repos/{_quote(owner)}/{_quote(repo)}/pulls/{pull_number}",
            token=token,
        )

    def list_pull_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        token: str,
    ) -> list[dict[str, Any]]:
        # PR에서 바뀐 파일 목록(파일별 patch/추가·삭제 줄 수 포함)을 가져온다.
        return self.paginated_get(
            f"/repos/{_quote(owner)}/{_quote(repo)}/pulls/{pull_number}/files",
            token=token,
        )

    def list_check_runs(
        self,
        owner: str,
        repo: str,
        ref: str,
        token: str,
    ) -> list[dict[str, Any]]:
        # 특정 커밋(ref)에 붙은 CI 체크 결과(lint/test 등)를 가져온다.
        payload = self.request_json(
            "GET",
            f"/repos/{_quote(owner)}/{_quote(repo)}/commits/{_quote(ref)}/check-runs",
            token=token,
        )
        check_runs = payload.get("check_runs", [])
        # 응답 형태가 예상과 다르면(리스트가 아니면) 빈 리스트로 안전하게 처리한다.
        return check_runs if isinstance(check_runs, list) else []

    def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str,
        token: str,
    ) -> str | None:
        """특정 커밋(ref)에서 파일 하나의 텍스트 내용을 읽어 온다. 없으면 None.

        GitHub은 파일 내용을 base64로 인코딩해 주므로 디코딩해서 문자열로 돌려준다.
        정책 파일 읽기나 심층 리뷰의 파이썬 원본 첨부에 쓴다.
        """
        # URL에 넣을 수 있게 경로/ref를 인코딩한다. 경로의 "/"는 그대로 둔다(safe="/").
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(ref, safe="")
        try:
            payload = self.request_json(
                "GET",
                f"/repos/{_quote(owner)}/{_quote(repo)}/contents/{encoded_path}?ref={encoded_ref}",
                token=token,
            )
        except urllib.error.HTTPError as exc:
            # 404(파일 없음)는 오류가 아니라 "내용 없음"으로 다룬다. 그 외는 다시 던진다.
            if exc.code == 404:
                return None
            raise
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            return None
        # base64 문자열 중간의 줄바꿈을 제거한 뒤 디코딩한다.
        encoded_content = str(payload.get("content") or "").replace("\n", "")
        if not encoded_content:
            return ""
        # errors="replace": 깨진 바이트가 있어도 예외 없이 대체 문자로 처리한다.
        return base64.b64decode(encoded_content).decode("utf-8", errors="replace")

    def create_check_run(
        self,
        owner: str,
        repo: str,
        token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # GitHub Checks 화면에 표시될 체크 항목을 새로 만든다(리뷰 시작 시 "진행 중" 표시).
        return self.request_json(
            "POST",
            f"/repos/{_quote(owner)}/{_quote(repo)}/check-runs",
            token=token,
            data=payload,
        )

    def update_check_run(
        self,
        owner: str,
        repo: str,
        check_run_id: str | int,
        token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # 이미 만든 체크 항목의 상태/결과를 갱신한다(예: 리뷰 완료 → success).
        return self.request_json(
            "PATCH",
            f"/repos/{_quote(owner)}/{_quote(repo)}/check-runs/{check_run_id}",
            token=token,
            data=payload,
        )

    def paginated_get(self, path: str, token: str) -> list[dict[str, Any]]:
        """목록 API를 여러 페이지에 걸쳐 모두 가져와 하나의 리스트로 합친다.

        GitHub 목록 응답은 한 번에 최대 100개씩만 준다. 마지막 페이지(100개 미만)에
        닿거나 최대 10페이지(1000개)까지 돌면 멈춘다(무한 루프 방지).
        """
        items: list[dict[str, Any]] = []
        # 경로에 이미 ?가 있으면 &로, 없으면 ?로 쿼리 파라미터를 이어 붙인다.
        separator = "&" if "?" in path else "?"
        for page in range(1, 11):
            payload = self.request_json(
                "GET",
                f"{path}{separator}per_page=100&page={page}",
                token=token,
            )
            # 리스트가 아니거나 비어 있으면 더 볼 페이지가 없는 것.
            if not isinstance(payload, list) or not payload:
                break
            items.extend(item for item in payload if isinstance(item, dict))
            # 100개 미만이면 마지막 페이지이므로 그만 가져온다.
            if len(payload) < 100:
                break
        return items

    def request_json(
        self,
        method: str,
        path: str,
        token: str,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """모든 GitHub API 호출이 거쳐 가는 공통 HTTP 함수(GET/POST/PATCH/DELETE).

        data가 있으면 JSON 본문으로 실어 보내고, 응답 본문을 JSON으로 파싱해 돌려준다.
        """
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            self._url(path),
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        # with: 응답을 다 읽으면 연결을 자동으로 닫는 컨텍스트 매니저.
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
        return json.loads(response_body) if response_body else {}

    def _url(self, path: str) -> str:
        # 완전한 URL이면 그대로, 아니면 설정된 API 기본 주소 뒤에 경로를 붙인다.
        # rstrip/lstrip으로 "/"가 겹치거나 빠지지 않게 이어 붙인다.
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.settings.github_api_base_url.rstrip('/')}/{path.lstrip('/')}"

    def _private_key(self) -> str:
        # App 개인키를 설정값(문자열) 또는 파일 경로 둘 중 있는 쪽에서 읽어 정규화한다.
        if self.settings.github_app_private_key:
            return normalize_private_key(self.settings.github_app_private_key)
        if self.settings.github_app_private_key_path:
            return normalize_private_key(
                self.settings.github_app_private_key_path.read_text(encoding="utf-8")
            )
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH is required")


# @dataclass(frozen=True): 값만 담는 불변 데이터 상자(schemas.py 참고).
@dataclass(frozen=True)
class GitHubWebhookReviewPlan:
    """webhook 처리 결과. "이 이벤트로 무엇을 할지"를 담는다.

    status : "ready"(리뷰 진행) / "accepted"(다음 이벤트 대기) / "ignored"(무시).
    reason : 사람이 읽을 판단 근거(로그/응답용).
    requests : 실제로 실행할 리뷰 요청들(무시/대기면 빈 리스트).
    """

    status: str
    reason: str
    requests: list[ReviewRequest]


class GitHubWebhookProcessor:
    """받은 webhook 이벤트를 해석해 review_plan(무엇을 리뷰할지)을 결정한다."""

    # 리뷰를 시작할 만한 pull_request 액션들. 이 집합에 없는 액션은 무시한다.
    pull_request_actions = {"opened", "reopened", "synchronize", "ready_for_review"}

    def __init__(
        self,
        settings: Settings,
        client: GitHubAppClient | None = None,
    ) -> None:
        self.settings = settings
        # client를 안 주면 설정으로 기본 클라이언트를 만든다(테스트 시 가짜 주입 가능).
        self.client = client or GitHubAppClient(settings)

    def review_plan(
        self,
        event_name: str,
        delivery_id: str,
        payload: dict[str, Any],
    ) -> GitHubWebhookReviewPlan:
        """이벤트 종류(event_name)에 따라 알맞은 처리 분기로 넘기는 진입점."""
        if event_name == "ping":
            # GitHub이 webhook 설정 확인용으로 보내는 신호. 무시한다.
            return GitHubWebhookReviewPlan("ignored", "GitHub webhook ping", [])
        if event_name == "pull_request":
            return self._pull_request_plan(delivery_id, payload)
        if event_name == "check_suite":
            return self._check_payload_plan("check_suite", delivery_id, payload)
        if event_name == "check_run":
            # 사용자가 "심층 리뷰 실행" 버튼을 누른 경우는 별도 분기로 처리한다.
            if payload.get("action") == "requested_action":
                return self._requested_action_plan(delivery_id, payload)
            return self._check_payload_plan("check_run", delivery_id, payload)
        return GitHubWebhookReviewPlan("ignored", f"unsupported GitHub event: {event_name}", [])

    def _pull_request_plan(
        self,
        delivery_id: str,
        payload: dict[str, Any],
    ) -> GitHubWebhookReviewPlan:
        """pull_request 이벤트 처리: PR이 열리거나 갱신됐을 때 바로 리뷰할지 판단한다."""
        action = str(payload.get("action", ""))
        # 설정이 "체크 완료 후 리뷰" 모드면, PR 이벤트는 흘려보내고 체크 완료를 기다린다.
        if self.settings.github_webhook_review_mode not in {"pull_request", "all"}:
            return GitHubWebhookReviewPlan(
                "accepted",
                "waiting for check_suite or check_run completion",
                [],
            )
        if action not in self.pull_request_actions:
            return GitHubWebhookReviewPlan("ignored", f"unsupported pull_request action: {action}", [])

        pull_request = _dict(payload.get("pull_request"))
        # 초안(draft) PR은 아직 리뷰 대상이 아니므로 건너뛴다.
        if pull_request.get("draft"):
            return GitHubWebhookReviewPlan("ignored", "draft pull request", [])

        return GitHubWebhookReviewPlan(
            "ready",
            "pull_request event selected for review",
            [self._build_review_request(delivery_id, "pull_request", payload, pull_request)],
        )

    def _check_payload_plan(
        self,
        payload_key: str,
        delivery_id: str,
        payload: dict[str, Any],
    ) -> GitHubWebhookReviewPlan:
        """체크 이벤트(check_suite/check_run) 처리: CI가 끝난 뒤 리뷰를 시작하는 경로.

        payload_key로 두 이벤트를 한 함수로 다룬다("check_suite" 또는 "check_run").
        """
        # after_checks 모드에서는 개별 check_run은 무시하고 check_suite 완료만 기다린다
        # (같은 커밋에 리뷰가 여러 번 도는 것을 막기 위함).
        if (
            self.settings.github_webhook_review_mode == "after_checks"
            and payload_key == "check_run"
        ):
            return GitHubWebhookReviewPlan("accepted", "waiting for check_suite completion", [])
        if self.settings.github_webhook_review_mode not in {"after_checks", "all"}:
            return GitHubWebhookReviewPlan(
                "ignored",
                f"{payload_key} ignored by GITHUB_WEBHOOK_REVIEW_MODE",
                [],
            )
        action = str(payload.get("action", ""))
        # 체크가 아직 끝나지 않았으면 완료될 때까지 기다린다.
        if action != "completed":
            return GitHubWebhookReviewPlan("accepted", f"waiting for {payload_key} completion", [])

        check_payload = _dict(payload.get(payload_key))
        # 우리 App이 만든 체크가 완료된 신호라면 무시한다(내 리뷰가 내 리뷰를 부르는
        # 무한 반복 방지).
        if self.settings.github_app_id and (
            _nested_str(check_payload, "app", "id") == str(self.settings.github_app_id)
        ):
            return GitHubWebhookReviewPlan("ignored", "self check event", [])
        if payload_key == "check_run" and check_payload.get("name") == self.settings.github_check_run_name:
            return GitHubWebhookReviewPlan("ignored", "self check_run event", [])
        pull_requests = check_payload.get("pull_requests") or []
        if not isinstance(pull_requests, list) or not pull_requests:
            return GitHubWebhookReviewPlan("ignored", f"{payload_key} has no pull requests", [])

        # 이 체크에 연결된 PR마다 최신 PR 정보를 가져와 리뷰 요청을 만든다.
        requests: list[ReviewRequest] = []
        for pull_request_summary in pull_requests:
            pull_number = int(_dict(pull_request_summary).get("number", 0))
            if pull_number <= 0:
                continue
            repository = _repository(payload)
            installation_id = _installation_id(payload)
            token = self.client.installation_token(installation_id)
            pull_request = self.client.get_pull_request(
                repository["owner"],
                repository["name"],
                pull_number,
                token,
            )
            requests.append(
                self._build_review_request(delivery_id, payload_key, payload, pull_request, token)
            )

        if not requests:
            return GitHubWebhookReviewPlan("ignored", f"{payload_key} had no reviewable PR", [])
        return GitHubWebhookReviewPlan("ready", f"{payload_key} completed", requests)

    def _requested_action_plan(
        self,
        delivery_id: str,
        payload: dict[str, Any],
    ) -> GitHubWebhookReviewPlan:
        """"심층 리뷰 실행" 버튼 클릭(requested_action) 처리.

        버튼 identifier와 대상 체크 이름이 우리 것과 맞을 때만, review_mode를
        "deep_quality_review"로 지정한 리뷰 요청을 만든다.
        """
        requested_action = _dict(payload.get("requested_action"))
        identifier = str(requested_action.get("identifier") or "")
        # 우리가 만든 심층 리뷰 버튼이 아니면 무시한다.
        if identifier != DEEP_REVIEW_ACTION_IDENTIFIER:
            return GitHubWebhookReviewPlan(
                "ignored",
                f"unsupported check_run action: {identifier}",
                [],
            )

        check_run = _dict(payload.get("check_run"))
        if check_run.get("name") != self.settings.github_check_run_name:
            return GitHubWebhookReviewPlan("ignored", "requested action for another check_run", [])

        pull_requests = check_run.get("pull_requests") or []
        if not isinstance(pull_requests, list) or not pull_requests:
            return GitHubWebhookReviewPlan("ignored", "check_run action has no pull requests", [])

        repository = _repository(payload)
        installation_id = _installation_id(payload)
        token = self.client.installation_token(installation_id)
        requests: list[ReviewRequest] = []
        for pull_request_summary in pull_requests:
            pull_number = int(_dict(pull_request_summary).get("number", 0))
            if pull_number <= 0:
                continue
            pull_request = self.client.get_pull_request(
                repository["owner"],
                repository["name"],
                pull_number,
                token,
            )
            requests.append(
                self._build_review_request(
                    delivery_id,
                    "check_run.requested_action",
                    payload,
                    pull_request,
                    token,
                    # 이 두 값 때문에 심층 경로로 라우팅되고, 결과를 이 체크에 갱신한다.
                    review_mode="deep_quality_review",
                    check_run_id=str(check_run.get("id", "")),
                )
            )

        if not requests:
            return GitHubWebhookReviewPlan("ignored", "check_run action had no reviewable PR", [])
        return GitHubWebhookReviewPlan("ready", "manual deep review requested", requests)

    def _build_review_request(
        self,
        delivery_id: str,
        event_name: str,
        payload: dict[str, Any],
        pull_request: dict[str, Any],
        token: str | None = None,
        review_mode: str = "auto",
        check_run_id: str = "",
    ) -> ReviewRequest:
        """GitHub에서 PR 정보를 모두 긁어와 파이프라인 입력(ReviewRequest)으로 조립한다.

        PR 메타데이터 + 변경 파일 + 체크 결과 + 저장소 정책 문서를 모아 하나의 요청으로
        만든다. 심층 리뷰일 때는 파이썬 원본까지 붙여 복잡도 측정에 쓸 수 있게 한다.
        """
        repository = _repository(payload)
        installation_id = _installation_id(payload)
        # 토큰이 이미 있으면 재사용하고, 없으면 새로 발급한다.
        resolved_token = token or self.client.installation_token(installation_id)
        pull_number = int(pull_request.get("number", 0))
        base_sha = _nested_str(pull_request, "base", "sha")
        head_sha = _nested_str(pull_request, "head", "sha")
        files = self.client.list_pull_files(
            repository["owner"],
            repository["name"],
            pull_number,
            resolved_token,
        )
        checks = self.client.list_check_runs(
            repository["owner"],
            repository["name"],
            head_sha,
            resolved_token,
        )
        # 저장소에 정책 문서가 있으면 읽어 온다(RAG 컨텍스트로 쓰임). 없으면 None.
        repository_policy = self.client.get_file_content(
            repository["owner"],
            repository["name"],
            REPOSITORY_POLICY_PATH,
            base_sha,
            resolved_token,
        )
        changed_files = [_changed_file_payload(changed_file) for changed_file in files]
        # 심층 리뷰일 때만 파이썬 파일의 변경 전/후 전체 내용을 추가로 붙인다
        # (복잡도 측정에 파일 전체가 필요하기 때문).
        if review_mode == "deep_quality_review":
            changed_files = self._attach_python_sources(
                repository["owner"],
                repository["name"],
                files,
                changed_files,
                base_sha,
                head_sha,
                resolved_token,
            )

        # 모은 정보를 dict로 조립한 뒤 from_dict로 ReviewRequest 객체를 만든다.
        return ReviewRequest.from_dict(
            {
                "repository": {
                    "provider": "github",
                    "owner": repository["owner"],
                    "name": repository["name"],
                    "default_branch": repository["default_branch"],
                },
                "pull_request": {
                    "number": pull_number,
                    "title": str(pull_request.get("title", "")),
                    "author": _nested_str(pull_request, "user", "login"),
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "base_branch": _nested_str(pull_request, "base", "ref"),
                    "head_branch": _nested_str(pull_request, "head", "ref"),
                },
                "checks": [_check_result_payload(check) for check in checks],
                "changed_files": changed_files,
                # 정책 문서(마크다운)를 검색 단위(청크)로 쪼개 넣는다. 문서가 없으면
                # 빈 문자열이라 결과는 빈 리스트가 된다.
                "repository_policies": [
                    chunk.to_dict()
                    for chunk in split_policy_markdown(
                        REPOSITORY_POLICY_PATH,
                        repository_policy or "",
                    )
                ],
                "github": {
                    "run_id": delivery_id,
                    "delivery_id": delivery_id,
                    "event_name": event_name,
                    "installation_id": installation_id,
                    "check_run_id": check_run_id,
                },
                "review_mode": review_mode,
            }
        )

    def _attach_python_sources(
        self,
        owner: str,
        repo: str,
        raw_files: list[dict[str, Any]],
        changed_files: list[dict[str, Any]],
        base_sha: str,
        head_sha: str,
        token: str,
    ) -> list[dict[str, Any]]:
        """심층 리뷰용: 바뀐 파이썬 파일의 변경 전/후 전체 내용을 받아 붙인다.

        복잡도 측정은 diff만으로는 부족하고 파일 전체가 필요하다. API 호출이 많아지므로
        복잡도가 오를 만한 파일 최대 8개만 골라 여러 스레드로 동시에 내려받는다.
        """
        # 파일 경로 → GitHub 원본 파일 정보로 빠르게 찾기 위한 dict(딕셔너리 컴프리헨션).
        by_path = {str(item.get("filename") or ""): item for item in raw_files}
        # 파이썬 파일만 추려, 복잡도 관련 신호가 많은 순으로 정렬해 상위 8개만 고른다.
        # reverse=True: 점수가 높은(제어 흐름 변경이 많은) 파일이 앞에 오게 한다.
        candidates = sorted(
            (
                item
                for item in changed_files
                if str(item.get("path") or "").lower().endswith(".py")
            ),
            key=_complexity_source_priority,
            reverse=True,
        )[:8]

        # 파일 하나의 변경 전/후 내용을 GitHub에서 가져오는 내부 함수(스레드로 실행됨).
        def fetch(item: dict[str, Any]) -> tuple[str, str, str]:
            path = str(item.get("path") or "")
            raw_file = by_path.get(path, {})
            # 파일 이름이 바뀐 경우 변경 전 내용은 옛 경로(previous_filename)에서 읽는다.
            base_path = str(raw_file.get("previous_filename") or path)
            base_content = self.client.get_file_content(
                owner, repo, base_path, base_sha, token
            )
            head_content = self.client.get_file_content(
                owner, repo, path, head_sha, token
            )
            return path, base_content or "", head_content or ""

        # ThreadPoolExecutor: 여러 파일을 동시에(병렬로) 내려받아 대기 시간을 줄인다.
        # with 블록을 벗어나면 스레드 풀이 자동 정리된다. executor.map은 fetch를 각
        # 후보에 적용한 결과들을 돌려준다.
        with ThreadPoolExecutor(max_workers=min(4, len(candidates) or 1)) as executor:
            sources = {path: (base, head) for path, base, head in executor.map(fetch, candidates)}
        # 원래 변경 파일 목록에 방금 받은 원본 내용을 채워 새 dict로 돌려준다.
        # {**item, ...}: 기존 dict를 그대로 펼쳐 복사하고 두 키만 추가/덮어쓴다.
        # 후보에 없던(파이썬이 아닌) 파일은 sources에 없어 기본값 ("", "")이 들어간다.
        return [
            {
                **item,
                "base_content": sources.get(str(item.get("path") or ""), ("", ""))[0],
                "head_content": sources.get(str(item.get("path") or ""), ("", ""))[1],
            }
            for item in changed_files
        ]


# URL 경로에 값을 안전하게 넣기 위해 특수문자를 %인코딩한다("/"도 인코딩).
def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


# 값이 dict가 아니면(None 등) 빈 dict로 바꿔 준다. 아래 함수들이 GitHub 응답을
# 안전하게 파고들 수 있게 하는 방어용 도우미다.
def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested_str(payload: dict[str, Any], *keys: str) -> str:
    """중첩 dict를 여러 키로 안전하게 파고들어 문자열을 꺼낸다.

    *keys는 키를 여러 개 받는다는 뜻(예: _nested_str(pr, "base", "sha")는
    pr["base"]["sha"]에 해당). 중간에 값이 없어도 에러 없이 ""를 돌려준다.
    """
    value: Any = payload
    for key in keys:
        value = _dict(value).get(key)
    return "" if value is None else str(value)


def _repository(payload: dict[str, Any]) -> dict[str, str]:
    """webhook payload에서 저장소 owner/name/기본 브랜치를 안전하게 뽑아낸다.

    payload 형태가 이벤트마다 조금씩 달라, owner를 여러 위치에서 찾아본다.
    """
    repository = _dict(payload.get("repository"))
    owner_payload = _dict(repository.get("owner"))
    owner = str(owner_payload.get("login") or repository.get("owner") or "")
    name = str(repository.get("name") or "")
    # owner를 못 찾았고 "owner/name" 형태의 full_name이 있으면 "/" 기준으로 쪼갠다.
    # partition("/")은 (앞, "/", 뒤) 3개로 나누며, 가운데는 _로 버린다.
    if not owner and repository.get("full_name"):
        owner, _, name = str(repository["full_name"]).partition("/")
    return {
        "owner": owner,
        "name": name,
        "default_branch": str(repository.get("default_branch") or "main"),
    }


def _installation_id(payload: dict[str, Any]) -> str:
    # 토큰 발급에 꼭 필요한 installation.id를 꺼낸다. 없으면 진행할 수 없어 에러를 낸다.
    installation_id = _dict(payload.get("installation")).get("id")
    if not installation_id:
        raise RuntimeError("GitHub webhook payload does not include installation.id")
    return str(installation_id)


def _changed_file_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # GitHub의 파일 정보(filename 등)를 우리 스키마 키(path 등)로 옮겨 담는다.
    return {
        "path": payload.get("filename", ""),
        "status": payload.get("status", "modified"),
        "additions": payload.get("additions", 0),
        "deletions": payload.get("deletions", 0),
        "patch": payload.get("patch", ""),
    }


def _complexity_source_priority(payload: dict[str, Any]) -> tuple[int, int]:
    """파일이 복잡도에 얼마나 영향을 줄지 점수로 매긴다(원본 첨부 우선순위 정렬용).

    if/for/while/except 같은 제어 흐름 변경이 많을수록 복잡도가 오를 가능성이 크다.
    (제어흐름 개수, 변경 줄 수) 튜플을 돌려주며, 정렬은 앞 값을 먼저 비교한다.
    """
    patch = str(payload.get("patch") or "").lower()
    # diff에서 새로 추가/변경된 제어 흐름 키워드를 세기 위한 표식들.
    control_flow_markers = (
        " if ",
        "+if ",
        " elif ",
        "+elif ",
        " for ",
        "+for ",
        " while ",
        "+while ",
        " except ",
        "+except ",
        " case ",
        "+case ",
    )
    # 각 표식이 patch에 몇 번 나오는지 모두 더한다.
    control_flow_count = sum(patch.count(marker) for marker in control_flow_markers)
    changed_lines = int(payload.get("additions") or 0) + int(payload.get("deletions") or 0)
    return control_flow_count, changed_lines


def _check_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # GitHub 체크 결과를 우리 스키마 키로 옮긴다. summary는 있는 것 중 먼저 걸리는 값 사용.
    output = _dict(payload.get("output"))
    summary = str(output.get("summary") or output.get("title") or payload.get("html_url") or "")
    return {
        "kind": str(payload.get("name") or "check_run"),
        "status": str(payload.get("status") or "unknown"),
        "conclusion": str(payload.get("conclusion") or "unknown"),
        "summary": summary,
        "log_uri": payload.get("html_url"),
    }
