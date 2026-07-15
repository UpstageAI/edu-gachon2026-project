"""In-process coordination for stateful chat turns."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    references: int = 0


class SessionLockPool:
    """Serialize load → graph → save for one session without leaking lock keys.

    Supabase upserts alone cannot protect a read/modify/write turn from another
    concurrent request for the same session.  This lock covers one process; a
    database state-version check remains the follow-up for multi-worker scale.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _LockEntry] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        async with self._guard:
            entry = self._entries.get(session_id)
            if entry is None:
                entry = _LockEntry(lock=asyncio.Lock())
                self._entries[session_id] = entry
            entry.references += 1

        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.references -= 1
                if entry.references == 0:
                    self._entries.pop(session_id, None)

    @property
    def active_session_count(self) -> int:
        return len(self._entries)


class SlidingWindowRateLimiter:
    """Small in-process request limiter for anonymous MVP chat traffic."""

    def __init__(self, *, max_keys: int = 4096) -> None:
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._guard = asyncio.Lock()
        self._max_keys = max_keys

    async def acquire(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float = 60.0,
        now: float | None = None,
    ) -> float | None:
        """Consume one request or return seconds until the next slot."""

        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - window_seconds
        async with self._guard:
            entries = self._requests.setdefault(key, deque())
            self._requests.move_to_end(key)
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= limit:
                return max(0.001, window_seconds - (timestamp - entries[0]))
            entries.append(timestamp)
            while len(self._requests) > self._max_keys:
                self._requests.popitem(last=False)
            return None

    async def clear(self) -> None:
        async with self._guard:
            self._requests.clear()
