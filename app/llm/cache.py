"""On-disk replay cache for LLM responses.

Invariant: a cache key is a pure function of everything that could change the answer
(provider, model, role, schema, and the exact messages). If any of those differ, the
key differs, so a stale answer can never be served for a changed request.

Why this exists: during development the same scenario is re-run dozens of times.
Replaying makes those runs free AND deterministic, which is what allows the demo to be
reproducible. It is a development and resilience aid, never a substitute for the live
demo the rules require -- callers surface `from_cache` so the distinction is visible.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(".cache/llm_replay")


def make_key(
    *,
    provider: str,
    model: str,
    role: str,
    schema_name: str,
    messages: list[dict[str, str]],
) -> str:
    """Return a stable SHA-256 key for one logical request.

    `sort_keys=True` matters: dict ordering must not produce a different key for an
    identical request, or the cache silently never hits.
    """
    payload = json.dumps(
        {
            "provider": provider,
            "model": model,
            "role": role,
            "schema": schema_name,
            "messages": messages,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReplayCache:
    """A content-addressed JSON cache on disk.

    Never raises: a corrupt or unreadable entry is a miss, not a crash. A cache that
    can break the run is worse than no cache.
    """

    def __init__(self, directory: Path | None = None, *, enabled: bool = True) -> None:
        self.directory = Path(directory) if directory is not None else DEFAULT_CACHE_DIR
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached payload, or None on miss/disabled/corrupt."""
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("replay cache entry unreadable, treating as miss: %s", exc)
            return None
        if not isinstance(data, dict):
            return None
        return data

    def put(self, key: str, payload: dict[str, Any]) -> bool:
        """Write a payload. Returns False if the write failed; never raises."""
        if not self.enabled:
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = self._path(key).with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            tmp.replace(self._path(key))
        except OSError as exc:
            logger.warning("replay cache write failed: %s", exc)
            return False
        return True

    def clear(self) -> int:
        """Delete every cached entry. Returns how many were removed."""
        if not self.directory.is_dir():
            return 0
        removed = 0
        for entry in self.directory.glob("*.json"):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                logger.warning("could not remove cache entry %s", entry)
        return removed

    def count(self) -> int:
        """Number of entries currently cached."""
        if not self.directory.is_dir():
            return 0
        return sum(1 for _ in self.directory.glob("*.json"))
