# tests/ — pytest 테스트 (총 40개)

CI(`ci.yml`의 test job)와 push 전 로컬 검증(`uv run pytest`)에서 실행됩니다.

| 파일 | 검증 대상 |
|---|---|
| `test_graph.py` | 그래프 end-to-end (9개) — price 경로, off-topic 거절, 시나리오 1(쌀 vs 즉석밥), 가공식품 조회(다중 매칭/미존재/혼합 케이스) 등. **실제 LLM·DB를 호출**하므로 라우터 비결정성으로 간헐적 flake 가능 → 실패 시 해당 테스트만 재실행해서 판단 |
| `test_judge_price.py` | 가격 판정 로직 (13개) — parse_price(콤마/결측치), 비쌈/적정/쌈 경계값 |
| `test_normalize.py` | 단위 환산 (6개) — 쌀→밥 1공기 환산, 가공식품 별칭 |
| `test_router.py` | 라우터 (7개) — 키워드 폴백 라우터, LLM 라우터 경로 |
| `test_supabase_connection.py` | Supabase 연결 (5개) — price_cache 테이블 존재/UPSERT/조회 |
| `APItest.ipynb` | (노트북) 외부 API 수동 탐색용 — pytest 대상 아님, ruff 검사 제외 |

## 실행

```bash
uv run pytest              # 전체
uv run pytest tests/test_graph.py -v   # 특정 파일
```

환경변수(.env)의 `DATABASE_URL`, `UPSTAGE_API_KEY` 등이 필요합니다(그래프/DB 테스트가 실제 연결을 사용).
