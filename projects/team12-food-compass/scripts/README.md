# scripts/ — 데이터 수집·점검 스크립트

Supabase에 가격 데이터를 채우는 배치 스크립트들입니다. 매일 자동 실행되는 것과 수동 점검용이 섞여 있습니다.

| 파일 | 역할 | 실행 방식 |
|---|---|---|
| `fetch_kamis_snapshot.py` | KAMIS 전체 부류(6종) 시세 조회 → `price_snapshot` 적재 + 오래된 스냅샷 정리 | **GitHub Actions cron** (`kamis_daily_fetch.yml`, 매일 09:00 KST) 또는 수동 |
| `fetch_price_gokr_snapshot.py` | 참가격 품목/매장/가격 조회 → `price_gokr_*` 적재 + 매장 8권역 분류 | **GitHub Actions cron** (`price_gokr_daily_fetch.yml`, 매일 09:00 KST) 또는 수동 |
| `check_price_cache.py` | `price_cache` 테이블 save/get 동작을 터미널에서 수동 확인 | 수동 전용 |

## 수동 실행

```bash
# 로컬 (Windows PowerShell)
$env:PYTHONUTF8=1
.venv/Scripts/python.exe scripts/fetch_kamis_snapshot.py
```

cron이 실패했거나 당일 데이터를 즉시 채우고 싶을 때 GitHub Actions 탭에서 `workflow_dispatch`로 수동 트리거할 수도 있습니다.
