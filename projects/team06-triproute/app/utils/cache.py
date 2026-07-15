import hashlib
import json
import os
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

CACHE_DIR = Path("data/cache")
DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 카카오/TourAPI 응답은 하루 정도면 충분히 안정적이라 24시간으로 둠

# 캐시 파일 경로별 락. ThreadPoolExecutor로 병렬 조회하는 호출자(route_planner의
# _fill_missing_place_details 등)가 동일한 캐시 파일에 동시에 읽고/쓰는 것을 막기 위함
# (같은 content_id를 가리키는 서로 다른 place 항목이 있을 수 있어 파일 경합이 발생함).
# RLock인 이유: cached_call이 check-then-fetch-then-store 구간 전체를 하나의 락으로 감싸면서
# 그 안에서 _get_cached_raw/set_cached가 같은 경로에 대해 다시 락을 얻으므로(같은 스레드) 재진입이 필요함.
# 참조 카운트로 관리해서 더 이상 대기자가 없는 경로의 락은 즉시 dict에서 제거하고,
# 그렇지 않으면 프로세스 수명 동안 조회된 모든 (namespace, params) 조합이 영원히 쌓이게 된다.
_locks_guard = threading.Lock()
_path_locks: Dict[Path, threading.RLock] = {}
_path_lock_waiters: Dict[Path, int] = defaultdict(int)


@contextmanager
def _lock_for(path: Path) -> Iterator[None]:
    with _locks_guard:
        lock = _path_locks.setdefault(path, threading.RLock())
        _path_lock_waiters[path] += 1
    try:
        with lock:
            yield
    finally:
        with _locks_guard:
            _path_lock_waiters[path] -= 1
            if _path_lock_waiters[path] <= 0:
                _path_lock_waiters.pop(path, None)
                _path_locks.pop(path, None)


def _cache_path(namespace: str, params: Dict[str, Any]) -> Path:
    # 캐시 키는 namespace + 파라미터 조합의 해시. 파라미터 순서가 달라도 같은 키가 나오도록 정렬함.
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{namespace}_{digest}.json"


# get_cached/cached_call이 "캐시 없음"과 "캐시된 값이 None"을 구분할 수 있도록 쓰는 sentinel.
_MISSING = object()


def get_cached(namespace: str, params: Dict[str, Any], ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[Any]:
    """
    캐시된 응답이 있고 TTL 안이면 그 데이터를 반환하고, 없거나 만료됐으면 None을 반환합니다.
    """

    result = _get_cached_raw(namespace, params, ttl_seconds)
    return None if result is _MISSING else result


def _get_cached_raw(namespace: str, params: Dict[str, Any], ttl_seconds: int) -> Any:
    """
    get_cached와 동일하지만 캐시 미스를 _MISSING sentinel로 구분해서 반환한다
    (캐시된 데이터 자체가 None인 경우와 구분하기 위함).
    """

    path = _cache_path(namespace, params)
    with _lock_for(path):
        if not path.exists():
            return _MISSING

        try:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if time.time() - cached["cached_at"] > ttl_seconds:
                return _MISSING
            return cached["data"]
        except (json.JSONDecodeError, OSError, KeyError):
            return _MISSING


def set_cached(namespace: str, params: Dict[str, Any], data: Any) -> None:
    """
    API 응답을 JSON 캐시 파일로 저장합니다. 여러 스레드가 동시에 같은 캐시 파일에 쓰더라도
    임시 파일에 쓴 뒤 os.replace()로 원자적으로 교체하고, 파일 경로별 락으로 직렬화해서
    JSON이 깨지지 않도록 한다.
    """

    path = _cache_path(namespace, params)
    with _lock_for(path):
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"cached_at": time.time(), "params": params, "data": data}, f, ensure_ascii=False)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def cached_call(
    namespace: str,
    params: Dict[str, Any],
    fetch_fn: Callable[[], Any],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Any:
    """
    캐시가 있으면 그대로 반환하고, 없으면 fetch_fn()을 호출해서 결과를 캐시에 저장한 뒤 반환합니다.
    API 호출 결과를 그대로 감싸서 쓰는 용도 (예: kakao_mobility.get_route).
    캐시된 값이 None이더라도(예: 매칭 실패로 실제로 None을 반환하는 조회) 정상적으로
    캐시 히트로 처리되어 TTL 내에는 fetch_fn이 다시 호출되지 않는다.
    """

    path = _cache_path(namespace, params)
    with _lock_for(path):
        cached = _get_cached_raw(namespace, params, ttl_seconds)
        if cached is not _MISSING:
            return cached

        data = fetch_fn()
        set_cached(namespace, params, data)
        return data
