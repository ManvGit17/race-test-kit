"""The service every probe races against.

One endpoint, ``POST /events/1/reserve``, in one of two versions chosen by ``LAB_STRATEGY``:

* ``naive`` (default) counts the seats taken, compares with the capacity, then inserts. Two
  requests can both read "one seat left" and both insert: the oversell bug. This is the same
  check-then-insert as festrush-ticketing's ``naive`` strategy, with no artificial delay.
* ``row_lock`` takes ``SELECT ... FOR UPDATE`` on the event row first, so claims for one event
  run one at a time. It must never oversell; the lab runs it to show the check has no false
  alarms.

The ``/admin`` endpoints are for the harness and are hidden from the OpenAPI schema, so
Schemathesis only sees the reserve endpoint.
"""

import os
import threading
import time

from fastapi import FastAPI, HTTPException, Response
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

DSN = os.environ.get("LAB_PG_DSN", "postgresql://lab:lab@127.0.0.1:5433/lab")
STRATEGY = os.environ.get("LAB_STRATEGY", "naive")

pool = ConnectionPool(DSN, min_size=20, max_size=20, open=True)
app = FastAPI(title="prior-art lab")

# Server-side arrival time of every reserve request since the last reset. The spread between
# the first and the last is how tight the start really was, seen from the server.
_arrivals: list[float] = []
_arrivals_lock = threading.Lock()


class ReserveBody(BaseModel):
    student: int


@app.get("/health", include_in_schema=False)
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/events/{event_id}/reserve", status_code=201)
def reserve(event_id: int, body: ReserveBody, response: Response) -> dict[str, str]:
    with _arrivals_lock:
        _arrivals.append(time.perf_counter())
    with pool.connection() as conn:  # one transaction, committed when the block ends
        if STRATEGY == "row_lock":
            conn.execute("SELECT 1 FROM events WHERE id = %s FOR UPDATE", (event_id,))
        row = conn.execute(
            "SELECT e.capacity, (SELECT count(*) FROM reservations r WHERE r.event_id = e.id)"
            " FROM events e WHERE e.id = %s",
            (event_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "no such event")
        capacity, taken = row
        if taken >= capacity:
            response.status_code = 409
            return {"result": "full"}
        conn.execute(
            "INSERT INTO reservations (event_id, student) VALUES (%s, %s)",
            (event_id, body.student),
        )
    return {"result": "held"}


@app.post("/admin/reset", include_in_schema=False)
def reset(capacity: int = 10) -> dict[str, int]:
    with pool.connection() as conn:
        conn.execute("TRUNCATE reservations")
        conn.execute("UPDATE events SET capacity = %s WHERE id = 1", (capacity,))
    with _arrivals_lock:
        _arrivals.clear()
    return {"capacity": capacity}


@app.get("/admin/state", include_in_schema=False)
def state() -> dict[str, object]:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT capacity, (SELECT count(*) FROM reservations WHERE event_id = 1)"
            " FROM events WHERE id = 1"
        ).fetchone()
    assert row is not None
    with _arrivals_lock:
        arrivals = list(_arrivals)
    spread = (max(arrivals) - min(arrivals)) * 1000 if len(arrivals) > 1 else None
    return {
        "strategy": STRATEGY,
        "capacity": row[0],
        "taken": row[1],
        "requests": len(arrivals),
        "server_spread_ms": spread,
    }
