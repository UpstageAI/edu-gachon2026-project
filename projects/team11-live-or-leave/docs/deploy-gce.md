# GCE Docker Compose 배포 가이드

Day4 목표는 로컬 앱을 외부에서 호출 가능한 HTTP 서비스로 올리고, GitHub Actions에서
테스트가 자동 실행되는 최소 운영 형태를 만드는 것이다.

## 배포 구성

- `api`: FastAPI, `http://<VM_EXTERNAL_IP>:8000`
- `ui`: Streamlit 지도 UI, `http://<VM_EXTERNAL_IP>:8501`
- 같은 Docker 이미지를 사용하고 `command`만 다르게 실행한다.
- `.env`로 API 키와 런타임 옵션을 주입한다.
- `dataset/` 원본 CSV는 이미지에 넣지 않고 VM의 로컬 디렉터리를 volume으로 마운트한다.

## VM 준비

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

권한 반영을 위해 SSH를 한 번 다시 접속한다.

## 앱 배포

```bash
git clone <REPOSITORY_URL>
cd live-or-leave-team
cp .env.example .env
vi .env
```

`.env`에는 최소한 아래 값을 넣는다.

```bash
UPSTAGE_API_KEY=...
SOLAR_MODEL=solar-pro2-251215
UPSTAGE_API_BASE=https://api.upstage.ai/v1
USE_MOCK_LLM=0
```

(선택) Solar 호출을 Langfuse로 추적하고 싶으면 같은 `.env`에 아래도 추가한다.
비워두면 `solar_llm.py`가 무시하고 평소처럼 동작한다.

```bash
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```

`solar_llm.py`의 `_build_parse_system()`이 매 질문마다 업종 목록을 만들려고
`dataset/소상공인시장진흥공단_상가(상권)정보_서울.csv`를 읽으므로, **실제 Solar
경로(mock이 아닌)를 쓰는 한 업종 관련 질문 여부와 무관하게 이 파일이 항상
있어야 한다.** 없으면 모든 질문에서 `FileNotFoundError`로 실패한다. VM의 프로젝트
루트에 이 CSV 하나만 별도로 준비하면 되고(나머지 `dataset/` 원본은 빌드 스크립트
전용이라 불필요), 이 디렉터리는 git과 Docker 이미지에는 포함하지 않는다.

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

GCE 방화벽에서 TCP `8000`, `8501`을 허용하면 외부에서 아래 주소로 확인할 수 있다.

```text
http://<VM_EXTERNAL_IP>:8000/health
http://<VM_EXTERNAL_IP>:8501
```

## CI/CD 확인

`.github/workflows/ci.yml`은 push/PR마다 다음을 실행한다.

- Python 3.12 의존성 설치
- `python -m pytest tests/`
- `docker build -t live-or-leave:ci .`

`.github/workflows/cd.yml`은 `workflow_run`으로 CI를 지켜보다가, **main 브랜치에서
CI가 성공으로 끝난 경우에만** 전용 SSH 배포키(`GCE_SSH_PRIVATE_KEY` GitHub Secret)로
VM에 접속해 `git pull` + `docker compose up -d --build`를 실행한다. PR에서는
CI만 돌고 CD는 트리거되지 않는다. VM 외부 IP는 고정(static) IP로 승격해둬야
CD 스크립트와 발표 URL이 VM 재시작 후에도 깨지지 않는다.

접속 대상 IP·계정명은 `cd.yml`에 하드코딩하지 않고 `GCE_HOST`/`GCE_USER` GitHub
Secret으로 관리한다. VM을 새로 만들어 고정 IP가 바뀌면, 코드 수정 없이
`gh secret set GCE_HOST` / `gh secret set GCE_USER`로 Secret 값만 갱신하면 된다.

최종 발표 산출물로는 GitHub Actions(CI, CD 각각)의 초록색 통과 화면과 GCE 외부
접속 URL을 캡처한다.

## 발표 데모 운영 팁

- API 키가 없거나 UI 디자인만 확인할 때는 `.env`에서 `USE_MOCK_LLM=1`로 둔다.
- 실제 LLM 답변 품질을 보여줄 때는 `USE_MOCK_LLM=0`과 `UPSTAGE_API_KEY`가 필요하다.
- 실제 Solar 경로를 쓰려면 업종 질문 여부와 무관하게 위 CSV 1개가 항상 있어야 한다(위 참고).
- Kakao Local API를 쓰려면 `KAKAO_REST_API_KEY`도 채운다 — 없으면 CSV 밖 업종(클라이밍장 등)
  필터만 비활성화되고 나머지 기능은 그대로 동작한다.
- F19처럼 소음/방음 등 현재 데이터가 부족한 조건은 추천을 꾸미기보다 부족 조건을 명시하는 방향으로 보여준다.
- `LANGFUSE_*` 키를 넣어뒀다면, 데모 중 실제로 들어온 질문·응답·지연시간을
  Langfuse Tracing 대시보드(cloud.langfuse.com)에서 실시간으로 보여줄 수 있다.
