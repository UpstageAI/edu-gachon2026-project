#!/bin/bash
set -e

if [ ! -f .env ]; then
  cp .env.example .env
fi

uv sync
echo 'Policy Compass: http://localhost:8000'
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
