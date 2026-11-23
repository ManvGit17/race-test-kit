"""Shared by every probe: where the lab app is, how many clients, and one way to send.

Every thread-based probe uses the same pre-warmed clients (one TCP connection each, opened
before the race), so the probes differ only in how they start the requests, not in
connection setup. Each send records when it started and what came back; ``conftest.py``
writes that to ``LAB_OUT`` when the pytest session ends.
"""

import json
import os
import ssl
import threading
import time
from pathlib import Path

import httpx

URL = os.environ.get("LAB_URL", "http://127.0.0.1:8765")
CLIENTS = int(os.environ.get("LAB_CLIENTS", "50"))
SEATS = int(os.environ.get("LAB_SEATS", "10"))
OUT = os.environ.get("LAB_OUT")
_SSL = ssl.create_default_context()

_starts: list[float] = []
_statuses: list[int] = []
_extra: dict[str, object] = {}
_lock = threading.Lock()


def warm_clients(n: int = CLIENTS) -> list[httpx.Client]:
    # One SSL context for all: httpx builds a new one per client otherwise, which costs
    # about 140 ms each on Windows even for plain http (measured in this lab).
    clients = [httpx.Client(base_url=URL, timeout=30, verify=_SSL) for _ in range(n)]
    for client in clients:
        client.get("/health")  # open the connection now, not inside the race
    return clients


def post(client: httpx.Client, student: int) -> int:
    started = time.perf_counter()
    status = client.post("/events/1/reserve", json={"student": student}).status_code
    with _lock:
        _starts.append(started)
        _statuses.append(status)
    return status


def note(status: int, started: float) -> None:
    """For probes that send with their own client (asyncio)."""
    with _lock:
        _starts.append(started)
        _statuses.append(status)


def extra(**values: object) -> None:
    _extra.update(values)


def write_out() -> None:
    if not OUT:
        return
    spread = (max(_starts) - min(_starts)) * 1000 if len(_starts) > 1 else None
    data = {
        "sent": len(_statuses),
        "statuses": {str(s): _statuses.count(s) for s in sorted(set(_statuses))},
        "client_spread_ms": spread,
        **_extra,
    }
    Path(OUT).write_text(json.dumps(data), encoding="utf-8")
