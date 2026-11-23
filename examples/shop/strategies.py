"""Four ways to hold one seat, ported from festrush-ticketing's ``inventory.py``.

Every strategy answers "may this student hold a seat at this event?" and inserts the same
``shop_reservations`` row when the answer is yes. They differ only in how they stop two
requests from taking the last seat at once:

* ``naive``          counts the reservations, compares with the capacity, then inserts. Two
                     requests can both see one seat left. **Broken on purpose**: the
                     reference bug the plugin must keep catching.
* ``row_lock``       locks the event row (``SELECT ... FOR UPDATE``) first, so claims for one
                     event run one at a time.
* ``atomic_update``  inserts, then ``UPDATE ... SET claimed = claimed + 1 WHERE claimed <
                     capacity``; the database decides in one statement. No row updated means
                     sold out, and the insert is rolled back.
* ``skip_locked``    inserts, then takes a free seat row with ``FOR UPDATE SKIP LOCKED``, so
                     concurrent buyers take different rows instead of queueing on one. When the
                     only free seats are locked by claims still in flight, it waits briefly and
                     looks again, then answers "busy".

Each runs inside one transaction opened by ``reserve``.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable
from typing import Any

import psycopg
import psycopg.errors

Conn = psycopg.Connection[Any]

STRATEGIES = ("naive", "row_lock", "atomic_update", "skip_locked")


class Outcome(enum.Enum):
    HELD = "held"
    FULL = "full"
    ALREADY = "already"  # this student already holds a seat at this event
    BUSY = "busy"  # skip_locked only: free seats exist but are locked by claims in flight
    NO_EVENT = "no_event"


class _Rollback(Exception):
    """Undo the transaction and answer with this outcome."""

    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome


_INSERT = (
    "INSERT INTO shop_reservations (event_id, student) VALUES (%s, %s)"
    " ON CONFLICT (event_id, student) DO NOTHING RETURNING id"
)


def _one(conn: Conn, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
    row: tuple[Any, ...] | None = conn.execute(query, params).fetchone()
    return row


def _naive(conn: Conn, event_id: int, student: int) -> Outcome:
    row = _one(
        conn,
        "SELECT e.capacity, (SELECT count(*) FROM shop_reservations r WHERE r.event_id = e.id)"
        " FROM shop_events e WHERE e.id = %s",
        (event_id,),
    )
    if row is None:
        return Outcome.NO_EVENT
    capacity, taken = row
    if taken >= capacity:
        return Outcome.FULL
    # Another request may have inserted since the count above: that is the bug.
    if _one(conn, _INSERT, (event_id, student)) is None:
        return Outcome.ALREADY
    return Outcome.HELD


def _row_lock(conn: Conn, event_id: int, student: int) -> Outcome:
    row = _one(conn, "SELECT capacity FROM shop_events WHERE id = %s FOR UPDATE", (event_id,))
    if row is None:
        return Outcome.NO_EVENT
    taken = _one(conn, "SELECT count(*) FROM shop_reservations WHERE event_id = %s", (event_id,))
    assert taken is not None
    if taken[0] >= row[0]:
        return Outcome.FULL
    if _one(conn, _INSERT, (event_id, student)) is None:
        return Outcome.ALREADY
    return Outcome.HELD


def _atomic_update(conn: Conn, event_id: int, student: int) -> Outcome:
    # Insert first: a duplicate request is refused without touching the shared counter.
    if _one(conn, _INSERT, (event_id, student)) is None:
        return Outcome.ALREADY
    claimed = _one(
        conn,
        "UPDATE shop_events SET claimed = claimed + 1"
        " WHERE id = %s AND claimed < capacity RETURNING id",
        (event_id,),
    )
    if claimed is None:
        raise _Rollback(Outcome.FULL)  # undoes the reservation row
    return Outcome.HELD


def _skip_locked(conn: Conn, event_id: int, student: int) -> Outcome:
    made = _one(conn, _INSERT, (event_id, student))
    if made is None:
        return Outcome.ALREADY
    for attempt in range(4):
        seat = _one(
            conn,
            "SELECT id FROM shop_seats WHERE event_id = %s AND reservation_id IS NULL"
            " ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED",
            (event_id,),
        )
        if seat is not None:
            conn.execute(
                "UPDATE shop_seats SET reservation_id = %s WHERE id = %s", (made[0], seat[0])
            )
            return Outcome.HELD
        # No unlocked free seat. If free seats exist they are locked by claims still in
        # flight, which may yet roll back, so wait a moment and look again before "full".
        free = _one(
            conn,
            "SELECT 1 FROM shop_seats WHERE event_id = %s AND reservation_id IS NULL LIMIT 1",
            (event_id,),
        )
        if free is None:
            raise _Rollback(Outcome.FULL)
        if attempt < 3:
            time.sleep(0.005 * (attempt + 1))
    raise _Rollback(Outcome.BUSY)


_BY_NAME: dict[str, Callable[[Conn, int, int], Outcome]] = {
    "naive": _naive,
    "row_lock": _row_lock,
    "atomic_update": _atomic_update,
    "skip_locked": _skip_locked,
}


def reserve(conn: Conn, strategy: str, event_id: int, student: int) -> Outcome:
    """Hold one seat for a student. Either the seat is held afterwards, or nothing changed."""
    try:
        with conn.transaction():
            return _BY_NAME[strategy](conn, event_id, student)
    except _Rollback as stop:
        return stop.outcome
    except psycopg.errors.ForeignKeyViolation:  # atomic_update and skip_locked insert first
        return Outcome.NO_EVENT
