# Server Deployment Settings

이 문서는 GCP VM + WIF 기반 자동 배포를 위해 필요한 설정을 한 곳에 정리한다.

현재 배포 기준:

```text
main push
→ CI 성공
→ Deploy to GCP VM workflow 자동 실행
→ GitHub Actions에서 Docker image build
→ image tar + runtime 파일을 IAP 터널로 VM에 업로드
→ VM에서 docker load
→ docker compose up -d --no-build
→ /healthz 확인
```

## 설정 분리 기준

```text
GitHub Variables
→ 비밀은 아니지만 GitHub Actions 배포 workflow가 알아야 하는 값

GitHub Secrets
→ GitHub Actions가 GCP에 접근하기 위해 필요한 WIF 인증 값

VM .env
→ 실행 중인 API 컨테이너가 사용하는 앱 설정과 런타임 비밀값
→ Caddy 사용 시 DOMAIN, COMPOSE_PROFILES=edge 포함

GCP Secret Manager
→ 현재 구현에서는 필수 아님. VM .env 대신 쓰려면 별도 주입 로직 필요
```

## GitHub Repository Variables

Repository Settings → Secrets and variables → Actions → Variables에 설정한다.

필수:

```text
GCP_PROJECT_ID=<GCP Project ID>
GCP_ZONE=<VM Zone>
GCE_INSTANCE=<VM instance name>
```

권장:

```text
AI_REVIEWER_IMAGE_NAME=ai-code-review-agent-api
CD_DEPLOY_TARGET=gcp-vm
```

`CD_DEPLOY_TARGET` 값:

```text
gcp-vm
→ main CI 성공 후 GCP VM까지 자동 배포

local-only
→ image build 검증만 수행하고 GCP VM 배포는 건너뜀
```

확인 방법:

```bash
gcloud projects list
gcloud config get-value project
gcloud compute instances list
```

`GCP_WORKLOAD_IDENTITY_PROVIDER`에 들어가는 project number는 다음으로 확인한다.

```bash
gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"
```

### GitHub Variables 값별 출처

| Key                      | 예시                       | 어디서 확인/정하는가                                                                | 설명                                                                                                |
| ------------------------ | -------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `GCP_PROJECT_ID`         | `charged-curve-501705-n9`  | GCP Console 상단 project selector 또는 `gcloud projects list`                       | GCP project 이름이 아니라 Project ID                                                                |
| `GCP_ZONE`               | `asia-northeast3-c`        | Compute Engine → VM instances → 대상 VM의 Zone 또는 `gcloud compute instances list` | 배포 대상 VM이 있는 zone                                                                            |
| `GCE_INSTANCE`           | `ai-code-review-agent`     | Compute Engine → VM instances → Name 또는 `gcloud compute instances list`           | 배포 대상 VM 이름                                                                                   |
| `AI_REVIEWER_IMAGE_NAME` | `ai-code-review-agent-api` | 직접 정함                                                                           | Actions에서 빌드하는 Docker image 이름. registry 주소가 아니라 VM에 `docker load`될 로컬 image 이름 |
| `CD_DEPLOY_TARGET`       | `gcp-vm`                   | 직접 정함                                                                           | `gcp-vm`이면 VM 배포, `local-only`면 image build 검증만 수행                                        |

확인 명령:

```bash
# 현재 gcloud가 바라보는 project id
gcloud config get-value project

# 접근 가능한 project 목록
gcloud projects list

# VM 이름과 zone 확인
gcloud compute instances list --project <PROJECT_ID>
```

## GitHub Repository Secrets

Repository Settings → Secrets and variables → Actions → Secrets에 설정한다.

```text
GCP_WORKLOAD_IDENTITY_PROVIDER=projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL_ID>/providers/<PROVIDER_ID>
GCP_SERVICE_ACCOUNT=github-deployer@<PROJECT_ID>.iam.gserviceaccount.com
```

### GitHub Secrets 값별 출처

| Key                              | 예시                                                                                                 | 어디서 확인/정하는가                                                                                                    | 설명                                                              |
| -------------------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL_ID>/providers/<PROVIDER_ID>` | GCP IAM → Workload Identity Federation → Provider 상세 또는 `gcloud iam workload-identity-pools providers describe ...` | GitHub Actions OIDC 토큰을 신뢰할 GCP provider resource name      |
| `GCP_SERVICE_ACCOUNT`            | `github-deployer@<PROJECT_ID>.iam.gserviceaccount.com`                                               | GCP IAM → Service Accounts 또는 `gcloud iam service-accounts list`                                                      | GitHub Actions가 WIF로 impersonate할 배포용 service account email |

확인 명령:

```bash
# project number 확인
gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"

# service account email 확인
gcloud iam service-accounts list --project <PROJECT_ID>

# Workload Identity Provider full resource name 확인
gcloud iam workload-identity-pools providers describe <PROVIDER_ID> \
  --workload-identity-pool=<POOL_ID> \
  --location=global \
  --project=<PROJECT_ID> \
  --format="value(name)"
```

`GCP_WORKLOAD_IDENTITY_PROVIDER`와 `GCP_SERVICE_ACCOUNT`는 값 자체가 앱 런타임 secret은
아니지만, 현재 workflow가 `secrets.GCP_WORKLOAD_IDENTITY_PROVIDER`,
`secrets.GCP_SERVICE_ACCOUNT`로 읽도록 되어 있으므로 GitHub Secrets에 넣는다.

GitHub Secrets에는 `UPSTAGE_API_KEY`, `GITHUB_APP_PRIVATE_KEY`, `LANGFUSE_SECRET_KEY` 같은
앱 런타임 비밀값을 넣지 않는다. 현재 workflow는 이 값을 컨테이너에 전달하지 않는다.

## GCP 준비 사항

필수 리소스:

```text
GCE VM
정적 외부 IP 또는 도메인
Docker CLI
Docker Compose plugin
IAP SSH 접근
Workload Identity Pool
GitHub OIDC Provider
배포용 Service Account
```

필수로 활성화할 GCP API:

```text
iamcredentials.googleapis.com
sts.googleapis.com
compute.googleapis.com
iap.googleapis.com
oslogin.googleapis.com
```

이번 배포 단계에서 `Unable to acquire impersonated credentials`와 함께
`IAM Service Account Credentials API has not been used ... or it is disabled`가 나오면
`iamcredentials.googleapis.com`이 꺼져 있는 상태다. GitHub Actions의 WIF 인증은 대상
service account를 impersonate하면서 IAM Service Account Credentials API를 사용하므로,
이 API가 꺼져 있으면 `gcloud compute scp`/`ssh` 단계에서 토큰 갱신이 실패한다.

활성화 명령:

```bash
gcloud services enable \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  compute.googleapis.com \
  iap.googleapis.com \
  oslogin.googleapis.com \
  --project <PROJECT_ID>
```

Console에서는 다음 위치에서 켤 수 있다.

```text
GCP Console
→ APIs & Services
→ Library
→ IAM Service Account Credentials API
→ Enable
```

API를 방금 켰다면 권한 전파에 몇 분이 걸릴 수 있다. 같은 에러가 바로 반복되면 잠시 후
workflow를 재실행한다.

권장 VM:

```text
OS: Ubuntu 22.04 이상
Instance name: ai-code-review-agent
Zone: asia-northeast3-c
Open ports: 80, 443
Internal app port: 8080
SSH: IAP 대역(35.235.240.0/20)만 허용 권장
```

Caddy를 사용할 경우 VM `.env`에 `COMPOSE_PROFILES=edge`와 `DOMAIN`을 설정한다. 실제
도메인이 없으면 정적 IP를 가리키는 sslip.io 도메인을 사용할 수 있다.

```text
정적 IP: 34.64.123.45
DOMAIN=34-64-123-45.sslip.io
```

배포용 service account에는 최소 다음 권한이 필요하다.

```text
roles/iap.tunnelResourceAccessor
roles/compute.viewer
roles/compute.osLogin 또는 roles/compute.osAdminLogin
roles/iam.serviceAccountUser
```

`roles/iam.serviceAccountUser`는 project 전체가 아니라 VM에 연결된 service account에 대해
부여해도 된다. 이번 에러처럼 `The user does not have access to service account
'<PROJECT_NUMBER>-compute@developer.gserviceaccount.com'`가 나오면, GitHub Actions가
impersonate하는 배포용 service account가 VM의 service account를 사용할 권한이 없는 상태다.

예시:

```bash
PROJECT_ID=charged-curve-501705-n9
PROJECT_NUMBER=1026819034842
DEPLOYER_SA=github-deployer@${PROJECT_ID}.iam.gserviceaccount.com
VM_ATTACHED_SA=${PROJECT_NUMBER}-compute@developer.gserviceaccount.com

gcloud iam service-accounts add-iam-policy-binding "${VM_ATTACHED_SA}" \
  --project "${PROJECT_ID}" \
  --member "serviceAccount:${DEPLOYER_SA}" \
  --role "roles/iam.serviceAccountUser"
```

VM에 기본 Compute Engine service account가 아닌 별도 service account를 붙였다면
`VM_ATTACHED_SA`를 해당 email로 바꾼다.

VM 접속 계정은 Docker를 실행할 수 있어야 한다. OS Login을 사용하는 경우 GitHub Actions가
impersonate하는 service account 기반 Linux 사용자가 `docker compose`를 실행할 수 있는지
반드시 확인한다.

## VM .env 위치

VM에 다음 파일을 미리 생성한다.

```text
~/ai-code-review-agent-deploy/.env
```

생성 예시:

```bash
mkdir -p ~/ai-code-review-agent-deploy
nano ~/ai-code-review-agent-deploy/.env
```

`.env`를 수정한 뒤 이미 실행 중인 컨테이너에 반영하려면 컨테이너 재생성이 필요하다.

```bash
cd ~/ai-code-review-agent-deploy
COMPOSE_FILE=docker-compose.yml docker compose -p ai-code-review-agent up -d --no-build --force-recreate
```

## VM .env Template

아래 값에서 `<...>`를 실제 값으로 바꾼다.

```env
APP_ENV=production
PORT=8080
COMPOSE_FILE=docker-compose.yml
COMPOSE_PROFILES=edge
DOMAIN=<domain-or-static-ip-sslip-domain>

AI_REVIEWER_TOKEN=<server-api-token>

PUBLISH_MODE=github_app
GITHUB_TOKEN=

GITHUB_WEBHOOK_SECRET=<github-app-webhook-secret>
GITHUB_WEBHOOK_REVIEW_MODE=after_checks
GITHUB_CHECK_RUN_NAME=AI Code Review
GITHUB_APP_ID=<github-app-id>
GITHUB_APP_PRIVATE_KEY=<github-app-private-key-pem-or-base64>
GITHUB_APP_PRIVATE_KEY_PATH=
GITHUB_API_BASE_URL=https://api.github.com

LLM_MODE=litellm
UPSTAGE_API_KEY=<upstage-api-key>
UPSTAGE_API_BASE_URL=https://api.upstage.ai/v1
SOLAR3_MODEL=solar-pro3
SOLAR3_LOW_REASONING_EFFORT=low
SOLAR3_MEDIUM_REASONING_EFFORT=medium
SOLAR3_HIGH_REASONING_EFFORT=high

LANGFUSE_PUBLIC_KEY=<langfuse-public-key>
LANGFUSE_SECRET_KEY=<langfuse-secret-key>
LANGFUSE_HOST=https://cloud.langfuse.com

STORAGE_BACKEND=postgres
RAG_BACKEND=postgres
POSTGRES_DB=reviewer
POSTGRES_USER=reviewer
POSTGRES_PASSWORD=<strong-postgres-password>
DATABASE_URL=postgresql://reviewer:<strong-postgres-password>@postgres:5432/reviewer

POLICY_ROOT=policies
LOCAL_DATA_DIR=.local-data
REVIEW_STORE_PATH=.local-data/reviews.json
COMMENT_OUTPUT_DIR=.local-data/comments
```

## VM .env 값별 출처

직접 정하는 값:

| Key                              | 예시                                                      | 설명                                                                |
| -------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| `APP_ENV`                        | `production`                                              | 운영 환경 표시용 값. 배포 VM에서는 `production` 권장                |
| `PORT`                           | `8080`                                                    | 컨테이너 API 포트. reverse proxy도 같은 포트로 넘겨야 함            |
| `COMPOSE_FILE`                   | `docker-compose.yml`                                      | VM에서는 image 실행만 하므로 이 값 고정                             |
| `COMPOSE_PROFILES`               | `edge`                                                    | VM에서 Caddy reverse proxy/TLS 서비스를 함께 실행하려면 `edge` 사용 |
| `DOMAIN`                         | `review.example.com` 또는 `34-64-123-45.sslip.io`         | Caddy가 HTTPS 인증서를 발급받을 도메인                              |
| `AI_REVIEWER_TOKEN`              | 긴 랜덤 문자열                                            | 내부 API(`/v1/reviews`, policy sync 등)를 보호하는 Bearer token     |
| `PUBLISH_MODE`                   | `github_app`                                              | 서버 배포에서는 GitHub App 방식 사용                                |
| `GITHUB_TOKEN`                   | 비움                                                      | GitHub App 방식에서는 사용하지 않음                                 |
| `GITHUB_WEBHOOK_REVIEW_MODE`     | `after_checks`                                            | CI 완료 이후 리뷰 실행                                              |
| `GITHUB_CHECK_RUN_NAME`          | `AI Code Review`                                          | GitHub PR Checks에 표시될 이름                                      |
| `GITHUB_APP_PRIVATE_KEY_PATH`    | 비움                                                      | private key를 env 값으로 넣으면 비워둠                              |
| `GITHUB_API_BASE_URL`            | `https://api.github.com`                                  | GitHub Enterprise가 아니면 기본값 사용                              |
| `LLM_MODE`                       | `litellm`                                                 | 실제 Solar3 호출 모드                                               |
| `UPSTAGE_API_BASE_URL`           | `https://api.upstage.ai/v1`                               | Upstage OpenAI-compatible API base URL                              |
| `SOLAR3_MODEL`                   | `solar-pro3`                                              | Upstage Solar Pro 3 model id                                        |
| `SOLAR3_LOW_REASONING_EFFORT`    | `low`                                                     | 단순 실패 리뷰용 추론 강도                                          |
| `SOLAR3_MEDIUM_REASONING_EFFORT` | `medium`                                                  | 정책 기반 기본 리뷰용 추론 강도                                     |
| `SOLAR3_HIGH_REASONING_EFFORT`   | `high`                                                    | 수동 심층 리뷰용 추론 강도                                          |
| `LANGFUSE_HOST`                  | `https://cloud.langfuse.com`                              | Langfuse Cloud 사용 시 기본값                                       |
| `STORAGE_BACKEND`                | `postgres`                                                | 운영에서는 Postgres 사용                                            |
| `RAG_BACKEND`                    | `postgres`                                                | 운영에서는 pgvector RAG 사용                                        |
| `POSTGRES_DB`                    | `reviewer`                                                | 직접 정하는 DB 이름                                                 |
| `POSTGRES_USER`                  | `reviewer`                                                | 직접 정하는 DB 사용자                                               |
| `POSTGRES_PASSWORD`              | 긴 랜덤 문자열                                            | 직접 정하는 DB 비밀번호. 첫 배포 전에 확정 권장                     |
| `DATABASE_URL`                   | `postgresql://reviewer:<password>@postgres:5432/reviewer` | 위 DB 값으로 직접 조립                                              |
| `POLICY_ROOT`                    | `policies`                                                | 배포 workflow가 업로드하는 정책 디렉터리                            |
| `LOCAL_DATA_DIR`                 | `.local-data`                                             | 런타임 로컬 데이터 저장 경로                                        |
| `REVIEW_STORE_PATH`              | `.local-data/reviews.json`                                | local fallback용 리뷰 저장 파일                                     |
| `COMMENT_OUTPUT_DIR`             | `.local-data/comments`                                    | local publish fallback용 댓글 저장 경로                             |

외부 서비스에서 가져오는 값:

| Key                      | 어디서 얻는가                                         | 설명                                   |
| ------------------------ | ----------------------------------------------------- | -------------------------------------- |
| `UPSTAGE_API_KEY`        | Upstage Console                                       | Solar3 API 호출용 키                   |
| `GITHUB_WEBHOOK_SECRET`  | 직접 생성 후 GitHub App Webhook Secret에 같은 값 입력 | GitHub webhook 서명 검증용 공유 비밀값 |
| `GITHUB_APP_ID`          | GitHub App 설정 화면                                  | App ID 값                              |
| `GITHUB_APP_PRIVATE_KEY` | GitHub App 설정 화면에서 private key 생성/다운로드    | installation token 발급용 private key  |
| `LANGFUSE_PUBLIC_KEY`    | Langfuse Project Settings                             | LiteLLM observability public key       |
| `LANGFUSE_SECRET_KEY`    | Langfuse Project Settings                             | LiteLLM observability secret key       |

값을 만드는 방법:

```bash
# AI_REVIEWER_TOKEN, GITHUB_WEBHOOK_SECRET, POSTGRES_PASSWORD 등에 사용
openssl rand -base64 32
```

GitHub App 값 확인 위치:

```text
GitHub → Developer settings 또는 Organization settings
→ GitHub Apps
→ 생성한 App 선택

App ID
→ General 화면에서 확인

Webhook Secret
→ 직접 생성한 랜덤 값을 Webhook secret 칸에 입력하고 VM .env에도 같은 값 입력

Private Key
→ Private keys 섹션에서 Generate a private key
→ 다운로드된 .pem 내용을 GITHUB_APP_PRIVATE_KEY에 넣음
```

`GITHUB_APP_PRIVATE_KEY`는 여러 줄 PEM을 그대로 넣을 수 있지만, `.env` 편집이 불편하면
base64 한 줄 값으로 넣는 방식을 권장한다.

```bash
base64 -w 0 path/to/github-app-private-key.pem
```

macOS에서는 다음을 사용한다.

```bash
base64 -i path/to/github-app-private-key.pem
```

Langfuse 값 확인 위치:

```text
Langfuse
→ Project Settings
→ API Keys
→ Public Key / Secret Key
```

Upstage 값 확인 위치:

```text
Upstage Console
→ API Keys
→ 새 key 생성 또는 기존 key 복사
```

주의:

```text
VM .env에는 COMPOSE_FILE=docker-compose.yml만 사용한다.
로컬 build override인 docker-compose.local.yml은 VM에 넣지 않는다.
AI_REVIEWER_IMAGE는 workflow가 배포 시점에 주입하므로 VM .env에 고정하지 않는다.
COMPOSE_PROFILES=edge를 쓰면 DOMAIN 값이 필수다.
POSTGRES_PASSWORD는 첫 DB volume 생성 전에 확정하는 것이 좋다.
```

## GitHub App 설정

GitHub App webhook URL:

```text
https://<domain-or-static-ip>/v1/github/webhooks
```

권한:

```text
Contents: Read
Pull requests: Read and write
Checks: Read and write
Metadata: Read
```

구독 이벤트:

```text
pull_request
check_suite
check_run
installation
installation_repositories
```

설치 대상:

```text
리뷰를 받을 organization 또는 repository에 GitHub App 설치
```

`GITHUB_WEBHOOK_REVIEW_MODE=after_checks`에서는 CI가 완료된 뒤 `check_suite.completed`
이벤트를 기준으로 리뷰가 실행된다. 수동 심층 리뷰 버튼은 `check_run.requested_action`
이벤트를 사용한다.

## Reverse Proxy / TLS

GitHub webhook은 외부 HTTPS URL이 필요하다. VM에서는 compose의 `caddy` 서비스가 80/443을
열고, 내부 API 포트 `8080`으로 프록시한다.

권장 구조:

```text
GitHub Webhook
→ https://<domain>/v1/github/webhooks
→ caddy TLS termination
→ http://api:8080
→ api container
```

현재 `Caddyfile`:

```text
{$DOMAIN} {
    encode zstd gzip
    reverse_proxy api:{$APP_PORT}
}
```

VM `.env`에서 `COMPOSE_PROFILES=edge`를 설정하지 않으면 `caddy` profile은 실행되지 않는다.

## GCP Secret Manager

현재 구현에서는 Secret Manager가 필수는 아니다. 앱 런타임 비밀값은 VM의
`~/ai-code-review-agent-deploy/.env`에서 읽는다.

Secret Manager로 옮길 수 있는 후보:

```text
UPSTAGE_API_KEY
GITHUB_WEBHOOK_SECRET
GITHUB_APP_PRIVATE_KEY
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
POSTGRES_PASSWORD
DATABASE_URL
AI_REVIEWER_TOKEN
```

다만 Secret Manager에만 값을 넣으면 현재 컨테이너는 읽지 못한다. Secret Manager를
사용하려면 배포 스크립트에서 secret을 가져와 `.env`를 생성하거나, 런타임에서 secret을
직접 읽는 별도 구현이 필요하다.

## 로컬 테스트 전환

로컬에서 image를 직접 빌드해 테스트하려면 `.env`에 다음처럼 둔다.

```env
COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml
AI_REVIEWER_IMAGE=ai-code-review-agent:local
COMPOSE_PROFILES=
DOMAIN=
APP_ENV=local
PORT=8080
```

실행:

```bash
docker compose up --build
```

로컬 배포 smoke test:

```bash
./scripts/local-deploy-test.sh
```

이 스크립트는 별도의 `infra/local-deploy/docker-compose.yml`을 사용하며, 기본값은
`LLM_MODE=mock`, `PUBLISH_MODE=local`이다.

## 첫 배포 체크리스트

1. GCP VM 생성 및 Docker/Compose 설치
2. IAP SSH 접속 가능 여부 확인
3. Workload Identity Pool, Provider, Service Account 생성
4. GitHub Variables/Secrets 등록
5. VM에 `~/ai-code-review-agent-deploy/.env` 생성
6. 도메인 또는 정적 IP 연결
7. `COMPOSE_PROFILES=edge`, `DOMAIN` 설정 후 Caddy/TLS 실행
8. GitHub App webhook URL 변경
9. GitHub App 권한과 이벤트 구독 확인
10. GitHub App을 대상 repository 또는 organization에 설치
11. main에 merge 또는 `Deploy to GCP VM` workflow 수동 실행
12. `/healthz`와 GitHub webhook delivery 확인

## 배포 후 확인 명령

VM에서:

```bash
cd ~/ai-code-review-agent-deploy
COMPOSE_FILE=docker-compose.yml docker compose -p ai-code-review-agent ps
COMPOSE_FILE=docker-compose.yml docker compose -p ai-code-review-agent logs -f api caddy
curl -fsS http://127.0.0.1:8080/healthz
```

외부에서:

```bash
curl -fsS https://<domain-or-static-ip>/healthz
```

GitHub에서:

```text
Repository → Settings → Webhooks 또는 GitHub App → Advanced → Recent Deliveries
PR → Checks → AI Code Review
```

## 자주 막히는 지점

```text
GCP_WORKLOAD_IDENTITY_PROVIDER 오타
→ google-github-actions/auth 단계 실패

GCP_SERVICE_ACCOUNT 권한 부족
→ gcloud compute ssh/scp 실패

IAP firewall 또는 IAM 누락
→ tunnel-through-iap 접속 실패

VM 사용자 Docker 권한 부족
→ docker compose 실행 실패

VM .env 없음
→ deploy script가 중단됨

GITHUB_APP_PRIVATE_KEY 형식 오류
→ installation token 발급 실패

GitHub App Checks 권한이 Read only
→ Check Run 생성/업데이트 실패

check_run 이벤트 미구독
→ 심층 리뷰 실행 버튼 클릭 이벤트가 서버로 오지 않음

POSTGRES_PASSWORD를 기존 volume 생성 후 변경
→ DATABASE_URL 인증 실패 가능
```
