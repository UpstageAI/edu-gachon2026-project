# frontend/ — Streamlit 챗봇 프론트엔드

| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit 기반 챗 UI — 백엔드 `/chat` SSE를 구독해 진행 상태(status)와 답변 토큰을 실시간 표시 |

## 실행

```bash
# 로컬
streamlit run frontend/app.py
# 백엔드 주소는 BACKEND_URL 환경변수로 지정 (기본 http://localhost:8000)
```

프로덕션에서는 `Dockerfile.frontend`로 빌드되어 `docker-compose.prod.yml`의 `frontend` 서비스(8501 포트)로 배포되고, `BACKEND_URL=http://api:8000`으로 api 컨테이너에 연결됩니다.
