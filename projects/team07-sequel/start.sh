#!/bin/bash
set -e
if [ ! -f .env ]; then echo ".env 파일이 없습니다. .env.example을 참고해 .env를 만들어주세요." && exit 1; fi
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 &
sleep 3
uv run streamlit run frontend/ui.py --server.port 8002 &
echo 'Backend: http://localhost:8001 | Frontend: http://localhost:8002'
wait
