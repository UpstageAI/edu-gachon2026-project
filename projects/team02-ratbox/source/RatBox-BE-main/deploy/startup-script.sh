#!/bin/bash
set -euo pipefail

export HOME=/var/lib/ratbox-home
mkdir -p "$HOME"

meta() {
  curl -s -f -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

IMAGE="$(meta app-image)"

mkdir -p /var/lib/ratbox
meta app-env > /var/lib/ratbox/.env

# Authenticate docker against Artifact Registry using the VM's service account.
docker-credential-gcr configure-docker --registries=asia-northeast3-docker.pkg.dev

docker network inspect ratbox-net >/dev/null 2>&1 || docker network create ratbox-net

docker rm -f ratbox-redis >/dev/null 2>&1 || true
docker run -d --name ratbox-redis --network ratbox-net --restart=always redis:7-alpine

docker pull "$IMAGE"
docker rm -f ratbox-api >/dev/null 2>&1 || true
docker run -d --name ratbox-api --network ratbox-net --restart=always \
  -p 8000:8000 --env-file /var/lib/ratbox/.env "$IMAGE"
