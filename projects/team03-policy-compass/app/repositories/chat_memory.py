from __future__ import annotations

import asyncio
import copy
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.http import log_external_api_error
from app.core.privacy import redact_sensitive_structure, redact_sensitive_text

logger = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 8
_MAX_MESSAGE_LENGTH = 4000
_MAX_LOCAL_SESSIONS = 2048
_REQUEST_TIMEOUT_SECONDS = 3
_LEGACY_CANDIDATE_SNAPSHOT_KEY = "__policy_compass_candidates_v1"


@dataclass
class ChatMemoryContext:
    messages: list[dict[str, str]] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)
    pending_request: dict[str, Any] = field(default_factory=dict)
    last_presented_candidates: list[dict[str, Any]] = field(default_factory=list)
    last_search_plan: dict[str, Any] = field(default_factory=dict)


def _safe_content(content: str) -> str:
    return redact_sensitive_text(content[:_MAX_MESSAGE_LENGTH])


def _split_legacy_pending(value: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Separate the pre-migration candidate snapshot from pending request data."""

    if not isinstance(value, dict):
        return {}, []
    pending = redact_sensitive_structure(value)
    raw_candidates = pending.pop(_LEGACY_CANDIDATE_SNAPSHOT_KEY, [])
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    return pending, candidates


def _legacy_pending_payload(
    pending_request: dict[str, Any],
    last_presented_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Preserve snapshots in existing JSONB until the additive column exists."""

    payload = dict(pending_request)
    if last_presented_candidates:
        payload[_LEGACY_CANDIDATE_SNAPSHOT_KEY] = last_presented_candidates
    return payload


class SupabaseChatMemoryRepository:
    """Persist explicit durable session state, with a bounded local fallback.

    LangGraph is deliberately compiled without a checkpointer.  This repository
    is therefore the single session-state boundary.  Local/CI environments keep
    the same multi-turn semantics in memory, while configured deployments mirror
    the state to Supabase.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = (settings.supabase_url or "").rstrip("/")
        self._key = settings.supabase_key or ""
        self._local_contexts: OrderedDict[str, ChatMemoryContext] = OrderedDict()
        self._remote_dirty_sessions: set[str] = set()
        self._local_lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._key)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    async def load(self, session_id: str) -> ChatMemoryContext:
        context = await self._load_local(session_id)
        if not self.is_configured or await self._is_remote_dirty(session_id):
            return context

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, headers=self._headers) as client:

            async def load_messages() -> None:
                try:
                    response = await client.get(
                        f"{self._base_url}/rest/v1/chat_logs",
                        params={
                            "session_id": f"eq.{session_id}",
                            "select": "id,role,content,created_at",
                            # A bulk user/assistant insert can share one
                            # timestamp; identity id makes their order stable.
                            "order": "created_at.desc,id.desc",
                            "limit": str(_MAX_HISTORY_MESSAGES),
                        },
                    )
                    response.raise_for_status()
                    rows = response.json()
                    remote_messages = [
                        {"role": row["role"], "content": _safe_content(row["content"])}
                        for row in reversed(rows)
                        if row.get("role") in {"user", "assistant"} and row.get("content")
                    ]
                    context.messages = remote_messages
                except Exception as exc:  # noqa: BLE001
                    log_external_api_error(logger, "Supabase 대화 이력 조회", exc)

            async def load_session() -> None:
                try:
                    response = await client.get(
                        f"{self._base_url}/rest/v1/chat_sessions",
                        params={
                            "session_id": f"eq.{session_id}",
                            "select": "profile,pending_request,last_presented_candidates,last_search_plan",
                            "limit": "1",
                        },
                    )
                    response.raise_for_status()
                    rows = response.json()
                    if rows:
                        pending_request, legacy_candidates = _split_legacy_pending(rows[0].get("pending_request") or {})
                        context.profile = redact_sensitive_structure(rows[0].get("profile") or {})
                        context.pending_request = pending_request
                        context.last_presented_candidates = redact_sensitive_structure(
                            rows[0].get("last_presented_candidates") or legacy_candidates
                        )
                        context.last_search_plan = redact_sensitive_structure(rows[0].get("last_search_plan") or {})
                except Exception as exc:  # noqa: BLE001
                    log_external_api_error(logger, "Supabase 세션 상태 조회", exc)
                    # Rolling deploy compatibility: first retry without the
                    # newest last_search_plan column while preserving the
                    # older candidate snapshot column.
                    try:
                        response = await client.get(
                            f"{self._base_url}/rest/v1/chat_sessions",
                            params={
                                "session_id": f"eq.{session_id}",
                                "select": "profile,pending_request,last_presented_candidates",
                                "limit": "1",
                            },
                        )
                        response.raise_for_status()
                        rows = response.json()
                        if rows:
                            pending_request, legacy_candidates = _split_legacy_pending(
                                rows[0].get("pending_request") or {}
                            )
                            context.profile = redact_sensitive_structure(rows[0].get("profile") or {})
                            context.pending_request = pending_request
                            context.last_presented_candidates = redact_sensitive_structure(
                                rows[0].get("last_presented_candidates") or legacy_candidates
                            )
                    except Exception as legacy_exc:  # noqa: BLE001
                        log_external_api_error(logger, "Supabase 이전 세션 상태 조회", legacy_exc)
                        try:
                            response = await client.get(
                                f"{self._base_url}/rest/v1/chat_sessions",
                                params={
                                    "session_id": f"eq.{session_id}",
                                    "select": "profile,pending_request",
                                    "limit": "1",
                                },
                            )
                            response.raise_for_status()
                            rows = response.json()
                            if rows:
                                pending_request, legacy_candidates = _split_legacy_pending(
                                    rows[0].get("pending_request") or {}
                                )
                                context.profile = redact_sensitive_structure(rows[0].get("profile") or {})
                                context.pending_request = pending_request
                                context.last_presented_candidates = redact_sensitive_structure(legacy_candidates)
                        except Exception as oldest_exc:  # noqa: BLE001
                            log_external_api_error(logger, "Supabase 레거시 세션 상태 조회", oldest_exc)

            await asyncio.gather(load_messages(), load_session())
        await self._store_local(session_id, context)
        return context

    async def save_turn(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_message: str,
        intent: str,
        profile: dict[str, Any],
        pending_request: dict[str, Any],
        last_presented_candidates: list[dict[str, Any]] | None = None,
        last_search_plan: dict[str, Any] | None = None,
    ) -> None:
        """Save a turn; ``None`` preserves durable candidate/search state."""

        was_remote_dirty = await self._is_remote_dirty(session_id)
        current = await self._load_local(session_id)
        messages = [
            *current.messages,
            {"role": "user", "content": _safe_content(user_message)},
            {"role": "assistant", "content": _safe_content(assistant_message)},
        ][-_MAX_HISTORY_MESSAGES:]
        context = ChatMemoryContext(
            messages=messages,
            profile=redact_sensitive_structure(profile),
            pending_request=redact_sensitive_structure(pending_request),
            last_presented_candidates=redact_sensitive_structure(
                current.last_presented_candidates if last_presented_candidates is None else last_presented_candidates
            ),
            last_search_plan=redact_sensitive_structure(
                current.last_search_plan if last_search_plan is None else last_search_plan
            ),
        )
        await self._store_local(session_id, context)

        if not self.is_configured:
            return

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, headers=self._headers) as client:

            async def save_messages() -> bool:
                try:
                    response = await client.post(
                        f"{self._base_url}/rest/v1/chat_logs",
                        json=[
                            {
                                "session_id": session_id,
                                "role": "user",
                                "content": _safe_content(user_message),
                                "intent": intent,
                            },
                            {
                                "session_id": session_id,
                                "role": "assistant",
                                "content": _safe_content(assistant_message),
                                "intent": intent,
                            },
                        ],
                    )
                    response.raise_for_status()
                    return True
                except Exception as exc:  # noqa: BLE001
                    log_external_api_error(logger, "Supabase 대화 이력 저장", exc)
                    return False

            async def save_session() -> bool:
                session_payload = {
                    "session_id": session_id,
                    "profile": context.profile,
                    "pending_request": context.pending_request,
                    "last_presented_candidates": context.last_presented_candidates,
                    "last_search_plan": context.last_search_plan,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
                try:
                    response = await client.post(
                        f"{self._base_url}/rest/v1/chat_sessions",
                        params={"on_conflict": "session_id"},
                        headers={"Prefer": "resolution=merge-duplicates"},
                        json=session_payload,
                    )
                    response.raise_for_status()
                    return True
                except Exception as exc:  # noqa: BLE001
                    log_external_api_error(logger, "Supabase 세션 상태 저장", exc)
                    try:
                        previous_schema_payload = {
                            key: value for key, value in session_payload.items() if key != "last_search_plan"
                        }
                        response = await client.post(
                            f"{self._base_url}/rest/v1/chat_sessions",
                            params={"on_conflict": "session_id"},
                            headers={"Prefer": "resolution=merge-duplicates"},
                            json=previous_schema_payload,
                        )
                        response.raise_for_status()
                        return True
                    except Exception as previous_schema_exc:  # noqa: BLE001
                        log_external_api_error(logger, "Supabase 이전 세션 상태 저장", previous_schema_exc)
                    try:
                        legacy_payload = {
                            key: value
                            for key, value in session_payload.items()
                            if key not in {"last_presented_candidates", "last_search_plan"}
                        }
                        legacy_payload["pending_request"] = _legacy_pending_payload(
                            context.pending_request,
                            context.last_presented_candidates,
                        )
                        response = await client.post(
                            f"{self._base_url}/rest/v1/chat_sessions",
                            params={"on_conflict": "session_id"},
                            headers={"Prefer": "resolution=merge-duplicates"},
                            json=legacy_payload,
                        )
                        response.raise_for_status()
                        return True
                    except Exception as legacy_exc:  # noqa: BLE001
                        log_external_api_error(logger, "Supabase 레거시 세션 상태 저장", legacy_exc)
                        return False

            messages_saved, session_saved = await asyncio.gather(save_messages(), save_session())
        # A later successful append does not prove that an earlier failed log
        # write was backfilled, so do not let stale remote history take over.
        await self._set_remote_dirty(session_id, was_remote_dirty or not (messages_saved and session_saved))

    async def clear_local(self) -> None:
        """Clear process-local state (primarily for test isolation)."""

        async with self._local_lock:
            self._local_contexts.clear()
            self._remote_dirty_sessions.clear()

    async def _load_local(self, session_id: str) -> ChatMemoryContext:
        async with self._local_lock:
            context = self._local_contexts.get(session_id)
            if context is None:
                return ChatMemoryContext()
            self._local_contexts.move_to_end(session_id)
            return copy.deepcopy(context)

    async def _store_local(self, session_id: str, context: ChatMemoryContext) -> None:
        async with self._local_lock:
            self._local_contexts[session_id] = copy.deepcopy(context)
            self._local_contexts.move_to_end(session_id)
            while len(self._local_contexts) > _MAX_LOCAL_SESSIONS:
                evicted_session_id, _ = self._local_contexts.popitem(last=False)
                self._remote_dirty_sessions.discard(evicted_session_id)

    async def _is_remote_dirty(self, session_id: str) -> bool:
        async with self._local_lock:
            return session_id in self._remote_dirty_sessions

    async def _set_remote_dirty(self, session_id: str, dirty: bool) -> None:
        async with self._local_lock:
            if dirty:
                self._remote_dirty_sessions.add(session_id)
            else:
                self._remote_dirty_sessions.discard(session_id)
