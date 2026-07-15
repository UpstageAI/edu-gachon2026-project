# SafetyTrip FE CI/CD

## CI

`.github/workflows/ci.yml` runs on pull requests, pushes to `main` or `develop`, and manual dispatch.

It checks:

- `npm ci`
- `npm run ci`
- Docker image build
- PR status comment
- Build artifact upload

The workflow uses concurrency, so older runs for the same branch are cancelled automatically.

## CD

`.github/workflows/cd.yml` runs after the `CI` workflow succeeds on `main`, or by manual dispatch.

It does:

- Build Docker image
- Push image to GitHub Container Registry
- Deploy to GCE over SSH when deploy secrets exist
- Health check `http://localhost:80/`
- Automatic rollback to the previous image if health check fails
- Manual rollback by running the workflow with `rollback=true`
- Deployment summary in the GitHub Actions run page

## Required GitHub Secrets

For image publishing, `GITHUB_TOKEN` is enough.

For GCE deployment, add:

```text
GCE_HOST
GCE_USER
GCE_SSH_KEY
GHCR_READ_TOKEN
```

`GHCR_READ_TOKEN` should be a GitHub token that can read packages from GHCR.

If these secrets are missing, the CD workflow still builds and pushes the image, then skips GCE deployment.

## GCE Server Prerequisites

Install Docker:

```bash
sudo apt-get update
sudo apt-get install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

Log out and back in after adding the user to the Docker group.

## Local Checks

```bash
npm run build
docker build -t safetytrip-fe:local .
docker run --rm -p 8080:80 safetytrip-fe:local
```

Open:

```text
http://localhost:8080
```
