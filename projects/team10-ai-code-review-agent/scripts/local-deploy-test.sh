#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [ -f .env ]; then
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      "" | \#*) continue ;;
    esac
    key="${line%%=*}"
    value="${line#*=}"
    case "${key}" in
      "" | *[!A-Za-z0-9_]* | [0-9]*) continue ;;
    esac
    if [ -z "${!key+x}" ]; then
      if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
        value="${value:1:${#value}-2}"
      fi
      export "${key}=${value}"
    fi
  done < .env
fi

COMPOSE_FILE="${LOCAL_DEPLOY_COMPOSE_FILE:-infra/local-deploy/docker-compose.yml}"
PROJECT_NAME="${LOCAL_DEPLOY_PROJECT:-ai-code-review-agent-local}"
AI_REVIEWER_IMAGE="${AI_REVIEWER_IMAGE:-ai-code-review-agent:local}"
PORT="${PORT:-8080}"
AI_REVIEWER_TOKEN="${AI_REVIEWER_TOKEN:-local-reviewer-token}"
GITHUB_WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-local-webhook-secret}"
LLM_MODE="${LLM_MODE:-mock}"
PUBLISH_MODE="${PUBLISH_MODE:-local}"

if ! command -v docker >/dev/null 2>&1; then
  echo "로컬 배포 테스트에는 Docker CLI가 필요합니다."
  echo "WSL 2를 사용 중이면 Docker Desktop의 WSL integration을 현재 distro에 켜주세요."
  exit 1
fi

if ! docker version >/dev/null 2>&1; then
  echo "Docker CLI는 있지만 현재 shell에서 Docker API에 접근할 수 없습니다."
  echo "Docker Desktop을 실행하고, WSL 2를 사용 중이면 현재 distro의 WSL integration을 켜주세요."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose가 필요합니다. Docker Desktop compose plugin 또는 docker-compose를 설치해주세요."
  exit 1
fi

export AI_REVIEWER_IMAGE
export PORT
export AI_REVIEWER_TOKEN
export GITHUB_WEBHOOK_SECRET
export LLM_MODE
export PUBLISH_MODE
export APP_ENV="${APP_ENV:-local-deploy}"
export STORAGE_BACKEND="${STORAGE_BACKEND:-postgres}"
export RAG_BACKEND="${RAG_BACKEND:-postgres}"
export POSTGRES_DB="${POSTGRES_DB:-reviewer}"
export POSTGRES_USER="${POSTGRES_USER:-reviewer}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-reviewer}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}}"
export GITHUB_WEBHOOK_REVIEW_MODE="${GITHUB_WEBHOOK_REVIEW_MODE:-after_checks}"

if [ "${LLM_MODE}" = "litellm" ] && [ -z "${UPSTAGE_API_KEY:-}" ]; then
  echo "LLM_MODE=litellm 실행에는 UPSTAGE_API_KEY가 필요합니다."
  exit 1
fi

if [ "${PUBLISH_MODE}" = "github_app" ]; then
  if [ -z "${GITHUB_APP_ID:-}" ]; then
    echo "PUBLISH_MODE=github_app 실행에는 GITHUB_APP_ID가 필요합니다."
    exit 1
  fi
  if [ -z "${GITHUB_APP_PRIVATE_KEY:-}" ] && [ -z "${GITHUB_APP_PRIVATE_KEY_PATH:-}" ]; then
    echo "PUBLISH_MODE=github_app 실행에는 GITHUB_APP_PRIVATE_KEY 또는 GITHUB_APP_PRIVATE_KEY_PATH가 필요합니다."
    exit 1
  fi
fi

echo "${AI_REVIEWER_IMAGE} 이미지를 빌드합니다."
docker build -t "${AI_REVIEWER_IMAGE}" .

echo "로컬 배포 stack을 실행합니다."
"${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" up -d --remove-orphans

api_url="http://127.0.0.1:${PORT}"

echo "API health check를 기다립니다."
for attempt in $(seq 1 40); do
  if curl -fsS "${api_url}/healthz" >/dev/null; then
    break
  fi
  if [ "${attempt}" = "40" ]; then
    "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" logs --tail=160 api postgres
    exit 1
  fi
  sleep 2
done

echo "정책 문서를 동기화합니다."
curl -fsS \
  -X POST "${api_url}/v1/repositories/local/policies/sync" \
  -H "Authorization: Bearer ${AI_REVIEWER_TOKEN}" \
  >/dev/null

if [ "${PUBLISH_MODE}" = "github_app" ]; then
  echo "GitHub App 인증을 확인합니다."
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" exec -T api \
    python - <<'PY'
from backend.app.core.config import Settings
from backend.app.services.github_app import GitHubAppClient

client = GitHubAppClient(Settings.from_env())
app = client.request_json("GET", "/app", token=client.create_jwt())
print(f"GitHub App 인증 완료: {app.get('slug') or app.get('name') or app.get('id')}")
PY
  echo "github_app 게시 모드에서는 sample-data에 installation_id가 없으므로 동기식 리뷰 smoke test를 건너뜁니다."
else
  echo "동기식 리뷰 smoke test를 실행합니다."
  curl -fsS \
    -X POST "${api_url}/v1/reviews?wait=true" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${AI_REVIEWER_TOKEN}" \
    --data @sample-data/review-request.json \
    >/dev/null
fi

echo "webhook signature smoke test를 실행합니다."
webhook_payload='{"zen":"local deploy webhook smoke"}'
webhook_signature="$(
  WEBHOOK_PAYLOAD="${webhook_payload}" WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET}" \
    python3 -c 'import hashlib, hmac, os; print("sha256=" + hmac.new(os.environ["WEBHOOK_SECRET"].encode(), os.environ["WEBHOOK_PAYLOAD"].encode(), hashlib.sha256).hexdigest())'
)"
curl -fsS \
  -X POST "${api_url}/v1/github/webhooks" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-GitHub-Delivery: local-deploy-smoke" \
  -H "X-Hub-Signature-256: ${webhook_signature}" \
  --data "${webhook_payload}" \
  >/dev/null

echo "로컬 배포 테스트가 완료되었습니다."
echo "API: ${api_url}"
echo "로그 확인: ${COMPOSE_CMD[*]} -f ${COMPOSE_FILE} -p ${PROJECT_NAME} logs -f api"
