"""In-memory API interaction logger for the developer debugging suite.

Captures FHIR and PSA HTTP request/response pairs (headers, timing, body) in a
bounded ring buffer. Nothing is written to disk — this is transient debug data.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

_MAX_ENTRIES = 200
_counter = itertools.count(1)
_lock = threading.Lock()
_entries: Deque[Dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)


def _truncate(body: Any, limit: int = 20000) -> Any:
    if isinstance(body, str) and len(body) > limit:
        return body[:limit] + f"\n... [truncated {len(body) - limit} chars]"
    return body


def record(
    *,
    target: str,
    method: str,
    url: str,
    request_headers: Optional[Dict[str, str]] = None,
    request_body: Any = None,
    status_code: Optional[int] = None,
    response_headers: Optional[Dict[str, str]] = None,
    response_body: Any = None,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Append an interaction to the log and return the stored entry."""
    entry = {
        "id": next(_counter),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "method": method.upper(),
        "url": url,
        "request_headers": _mask_headers(request_headers or {}),
        "request_body": _truncate(request_body),
        "status_code": status_code,
        "response_headers": dict(response_headers or {}),
        "response_body": _truncate(response_body),
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "error": error,
        "ok": error is None and (status_code is None or status_code < 400),
    }
    with _lock:
        _entries.appendleft(entry)
    return entry


def _mask_headers(headers: Dict[str, str]) -> Dict[str, str]:
    masked = {}
    for key, value in headers.items():
        if key.lower() in ("authorization", "x-api-key"):
            masked[key] = "********"
        else:
            masked[key] = value
    return masked


def list_entries(limit: int = 100) -> List[Dict[str, Any]]:
    with _lock:
        return list(itertools.islice(_entries, limit))


def get_entry(entry_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        for entry in _entries:
            if entry["id"] == entry_id:
                return entry
    return None


def clear() -> None:
    with _lock:
        _entries.clear()


class Timer:
    """Context manager that yields elapsed milliseconds."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0
