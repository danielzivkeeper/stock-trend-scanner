"""Small on-disk caches and rate limiters, so scanning ~500 stocks twice a day
stays fast and polite to free data sources.

Caches live in data_cache/*.json and are committed by the GitHub Action, so
they survive between runs. Everything here is thread-safe.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.environ.get("SCANNER_CACHE_DIR", os.path.join(ROOT, "data_cache"))


class RateLimiter:
    """At most one call per `interval` seconds across all threads."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


SEC_LIMIT = RateLimiter(0.12)    # SEC fair use: max 10 requests/second
WIKI_LIMIT = RateLimiter(0.15)   # Wikipedia's API throttles bursts; ~6/s keeps it happy
YAHOO_LIMIT = RateLimiter(0.05)


class JsonCache:
    """{key: {"t": unix time, "v": value}} persisted to one JSON file."""

    def __init__(self, name: str):
        self.path = os.path.join(CACHE_DIR, f"{name}.json")
        self._lock = threading.Lock()
        self._data: Optional[Dict[str, Any]] = None
        self.dirty = False

    def _load(self) -> Dict[str, Any]:
        if self._data is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                self._data = {}
        return self._data

    def get(self, key: str, max_age_hours: Optional[float]) -> Any:
        with self._lock:
            hit = self._load().get(key)
        if hit is None:
            return None
        if max_age_hours is not None and time.time() - hit["t"] > max_age_hours * 3600:
            return None
        return hit["v"]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._load()[key] = {"t": time.time(), "v": value}
            self.dirty = True

    def get_or_fetch(self, key: str, max_age_hours: Optional[float], fetch: Callable[[], Any]) -> Any:
        v = self.get(key, max_age_hours)
        if v is None:
            v = fetch()
            self.put(key, v)
        return v

    def prune(self, max_age_hours: float) -> None:
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            data = self._load()
            for k in [k for k, h in data.items() if h["t"] < cutoff]:
                del data[k]
                self.dirty = True

    def save(self) -> None:
        with self._lock:
            if not self.dirty or self._data is None:
                return
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, separators=(",", ":"), default=str)
            os.replace(tmp, self.path)
            self.dirty = False


_CACHES: Dict[str, JsonCache] = {}
_CACHES_LOCK = threading.Lock()


def cache(name: str) -> JsonCache:
    with _CACHES_LOCK:
        if name not in _CACHES:
            _CACHES[name] = JsonCache(name)
        return _CACHES[name]


def save_all() -> None:
    for c in list(_CACHES.values()):
        c.save()
