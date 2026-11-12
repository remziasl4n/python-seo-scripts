"""Disk cache for API responses, so reruns are free and don't spend quota.

Each entry is a JSON file under .cache/<namespace>/, named by a hash of the request:

    cache = Cache.from_settings()
    data = cache.get_or_set("autocomplete", {"q": "pool cost", "hl": "en"}, fetch)

`refresh=True` (the CLI's --refresh) ignores stored entries but still saves new ones.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from seo_toolkit.core.config import Settings, get_settings

_NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class Cache:
    def __init__(
        self,
        directory: Path,
        ttl_hours: float | None = 24,
        refresh: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """`ttl_hours=None` keeps entries forever."""
        self.directory = directory
        self.ttl_hours = ttl_hours
        self.refresh = refresh
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings | None = None, refresh: bool = False) -> Cache:
        settings = settings or get_settings()
        return cls(settings.cache_dir, settings.seo_cache_ttl_hours, refresh=refresh)

    @staticmethod
    def _encode_key(key: Any) -> str:
        return json.dumps(key, sort_keys=True, default=str, ensure_ascii=False)

    def _path(self, namespace: str, key: Any) -> Path:
        if not _NAMESPACE.match(namespace):
            raise ValueError(
                f"Cache namespace {namespace!r} must be lowercase, e.g. 'gemini.generate'."
            )
        digest = hashlib.sha256(self._encode_key(key).encode()).hexdigest()
        return self.directory / namespace / f"{digest}.json"

    def _load(self, namespace: str, key: Any) -> tuple[bool, Any]:
        if self.refresh:
            return False, None
        path = self._path(namespace, key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            created = float(entry["created"])
            value = entry["value"]
        except (OSError, ValueError, KeyError, TypeError):
            return False, None  # missing or unreadable entries count as a miss
        if self.ttl_hours is not None and self._clock() - created > self.ttl_hours * 3600:
            return False, None
        return True, value

    def get(self, namespace: str, key: Any) -> Any | None:
        """The stored value, or None if there is no fresh entry."""
        return self._load(namespace, key)[1]

    def set(self, namespace: str, key: Any, value: Any) -> None:
        """Store a JSON-serialisable value."""
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # No default=str here: a value that isn't JSON should fail, not come back as a string
        entry = {"created": self._clock(), "key": self._encode_key(key), "value": value}
        payload = json.dumps(entry, ensure_ascii=False)
        # Write to a temp file then rename, so an interrupted run never leaves half a file
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get_or_set(self, namespace: str, key: Any, compute: Callable[[], Any]) -> Any:
        """Return the stored value, or call `compute`, store its result and return it."""
        hit, value = self._load(namespace, key)
        if hit:
            return value
        value = compute()
        self.set(namespace, key, value)
        return value

    def clear(self, namespace: str | None = None) -> int:
        """Delete one namespace (or everything). Returns the number of entries removed."""
        target = self.directory / namespace if namespace else self.directory
        if namespace and not _NAMESPACE.match(namespace):
            raise ValueError(f"Cache namespace {namespace!r} must be lowercase.")
        if not target.exists():
            return 0
        count = sum(1 for _ in target.rglob("*.json"))
        shutil.rmtree(target)
        return count
