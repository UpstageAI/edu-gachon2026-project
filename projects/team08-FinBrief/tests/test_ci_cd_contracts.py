from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_workflow_runs_mock_compile_pytest_and_docker_build():
    text = read(".github/workflows/ci.yml")

    assert "name: FinBrief CI" in text
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert 'PYTHON_VERSION: "3.11"' in text
    assert "APP_ENV: test" not in text
    assert 'ENABLE_MOCK_DATA: "true"' in text
    assert 'FINBRIEF_LLM_STUB: "1"' in text
    assert 'FINBRIEF_IMAGE_STUB: "1"' in text
    assert 'DELIVERY_DRY_RUN: "true"' in text
    assert "actions/checkout@v7" in text
    assert "actions/setup-python@v6" in text
    assert "python -m compileall app" in text
    assert "mkdir -p .pytest_cache" in text
    assert (
        "python -m pytest -p no:cacheprovider --basetemp "
        ".pytest_cache/basetemp-ci --disable-warnings"
    ) in text
    assert "docker build -t finbrief:ci -f Dockerfile ." in text
    assert 'if [ "${{ needs.compile.result }}" != "success" ]' not in text


def test_cd_workflow_builds_ghcr_deploys_gce_and_keeps_rollback_state():
    text = read(".github/workflows/cd.yml")

    assert "name: FinBrief CD" in text
    assert "workflow_run:" in text
    assert "- FinBrief CI" in text
    assert "workflow_dispatch:" in text
    assert "actions/checkout@v7" in text
    assert "ghcr.io" in text
    assert "${{ github.repository }}/finbrief-api" in text
    assert "GCE_HOST" in text
    assert "GCE_USERNAME" in text
    assert "GCE_SSH_KEY" in text
    assert "SUPABASE_URL" in text
    assert "ENABLE_MOCK_DATA" in text
    assert "LANGFUSE_BASE_URL" in text
    assert "LANGFUSE_OTEL_HOST" in text
    assert "LANGFUSE_CAPTURE_IO" in text
    assert "FINBRIEF_TRACE_SALT" in text
    assert "docker compose up -d --force-recreate" in text
    assert "/api/v1/health" in text
    assert "APP_ENV: ${APP_ENV:-prod}" in text
    assert "printf 'APP_ENV=prod\\n'" in text
    assert "APP_ENV=production" not in text
    assert "APP_ENV:-production" not in text
    assert ".current_image" in text
    assert ".previous_image" in text
    assert "rollback" in text


def test_docker_runtime_contract_matches_finbrief_service():
    dockerfile = read("Dockerfile")
    compose = read("docker-compose.yml")
    dockerignore = read(".dockerignore")

    assert "FROM python:3.11-slim" in dockerfile
    assert "FROM python:3.11-slim AS builder" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "python -m pip wheel --wheel-dir /wheels ." in dockerfile
    assert "COPY --from=builder /wheels /wheels" in dockerfile
    assert "--no-index --find-links=/wheels" in dockerfile
    assert "USER finbrief" in dockerfile
    assert "APP_ENV=prod" in dockerfile
    assert "APP_ENV=production" not in dockerfile
    assert "FINBRIEF_REPORT_OUT=/app/reports" in dockerfile
    assert "/api/v1/health" in dockerfile
    assert 'CMD ["uvicorn", "app.main:app"' in dockerfile

    assert "name: finbrief" in compose
    assert "finbrief-api:" in compose
    assert "${SERVICE_PORT:-8000}:8000" in compose
    assert "APP_ENV: ${APP_ENV:-prod}" in compose
    assert "APP_ENV: ${APP_ENV:-production}" not in compose
    assert "FINBRIEF_REPORT_OUT: ${FINBRIEF_REPORT_OUT:-/app/reports}" in compose
    assert "finbrief_reports:" in compose
    assert "/api/v1/health" in compose

    assert ".env" in dockerignore
    assert ".git/" in dockerignore
    assert "project_docs/" in dockerignore
    assert "reports/*" in dockerignore
    assert "app/agents/out_reports/" in dockerignore


def test_gitignore_excludes_local_deploy_private_keys():
    text = read(".gitignore")

    assert "finbrief_gce_deploy*" in text


def test_env_example_documents_container_and_stub_variables():
    text = read(".env.example")

    assert "SERVICE_PORT=8000" in text
    assert "APP_IMAGE=finbrief:local" in text
    assert "FINBRIEF_LLM_STUB=1" in text
    assert "FINBRIEF_IMAGE_STUB=1" in text
    assert "FINBRIEF_REPORT_OUT=" in text
    assert "LANGFUSE_BASE_URL=" in text
    assert "LANGFUSE_OTEL_HOST=" in text
    assert "LANGFUSE_CAPTURE_IO=true" in text
    assert "LANGFUSE_FLUSH_ON_SHUTDOWN=false" in text
    assert "FINBRIEF_TRACE_SALT=" in text


def test_pyproject_includes_langfuse_observability_dependencies():
    text = read("pyproject.toml")

    assert '"langfuse>=4.0"' in text
    assert '"opentelemetry-sdk>=1.0"' in text
    assert '"opentelemetry-exporter-otlp>=1.0"' in text


def test_readme_documents_docker_and_ci_cd_paths():
    text = read("README.md")

    assert "## Docker 실행" in text
    assert "docker compose up -d --build" in text
    assert "## CI/CD" in text
    assert "FinBrief CI" in text
    assert "FinBrief CD" in text
    assert "GCE_HOST" in text
    assert "FINBRIEF_TRACE_SALT" in text
