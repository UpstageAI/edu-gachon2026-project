"""아침 배치 스케줄러 — 매일 지정 시각(KST)에 배치 1회 실행.

env:
  FINBRIEF_BATCH_HOUR    실행 시각(0~23, KST). 기본 7.
  FINBRIEF_BATCH_MINUTE  실행 분. 기본 0.
  FINBRIEF_RUN_ON_START  "1" 이면 기동 즉시 1회 실행(테스트 트리거).

실행:  python -m app.services.scheduler   (finbrief-scheduler 컨테이너의 command)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from app.services.batch import run_batch

KST = timezone(timedelta(hours=9))


def _seconds_until(hour: int, minute: int) -> float:
    now = datetime.now(KST)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _safe_run(tag: str) -> None:
    print(f"[scheduler] {tag} 배치 시작 {datetime.now(KST):%Y-%m-%d %H:%M} KST", flush=True)
    try:
        result = run_batch()
        print(
            f"[scheduler] 배치 완료 status={result.status} "
            f"cards={len(result.generated_cards)} deliveries={len(result.delivery_results)} "
            f"errors={len(result.errors)}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[scheduler] 배치 실패: {exc}", flush=True)


def main() -> None:
    hour = int(os.getenv("FINBRIEF_BATCH_HOUR", "7"))
    minute = int(os.getenv("FINBRIEF_BATCH_MINUTE", "0"))

    if os.getenv("FINBRIEF_RUN_ON_START") == "1":
        _safe_run("run-on-start")

    while True:
        wait = _seconds_until(hour, minute)
        print(f"[scheduler] 다음 실행까지 {wait / 3600:.2f}시간 대기 (매일 KST {hour:02d}:{minute:02d})", flush=True)
        time.sleep(wait)
        _safe_run("scheduled")


if __name__ == "__main__":
    main()
