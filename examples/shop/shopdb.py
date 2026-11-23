"""Direct database access for the shop's tests: create, reset and inspect an event.

Tests reset and check through the database, not through the app: the app is the thing under
test, so it must not also be the judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

SCHEMA = Path(__file__).with_name("schema.sql")


def apply_schema(conn: psycopg.Connection[Any]) -> None:
    conn.execute(SCHEMA.read_bytes())  # several statements, no parameters
    conn.commit()


def reset_event(conn: psycopg.Connection[Any], event_id: int, seats: int) -> None:
    """Empty the event and give it ``seats`` free seats."""
    with conn.transaction():
        conn.execute("DELETE FROM shop_seats WHERE event_id = %s", (event_id,))
        conn.execute("DELETE FROM shop_reservations WHERE event_id = %s", (event_id,))
        conn.execute(
            "INSERT INTO shop_events (id, capacity, claimed) VALUES (%s, %s, 0)"
            " ON CONFLICT (id) DO UPDATE SET capacity = EXCLUDED.capacity, claimed = 0",
            (event_id, seats),
        )
        conn.execute(
            "INSERT INTO shop_seats (event_id) SELECT %s FROM generate_series(1, %s)",
            (event_id, seats),
        )


@dataclass(frozen=True)
class EventState:
    capacity: int
    sold: int  # reservations: the source of truth, whatever the strategy
    claimed: int  # atomic_update's counter
    seats_taken: int  # skip_locked's seat rows pointing at a reservation


def state(conn: psycopg.Connection[Any], event_id: int) -> EventState | None:
    row = conn.execute(
        "SELECT e.capacity,"
        " (SELECT count(*) FROM shop_reservations r WHERE r.event_id = e.id),"
        " e.claimed,"
        " (SELECT count(*) FROM shop_seats s WHERE s.event_id = e.id"
        "   AND s.reservation_id IS NOT NULL)"
        " FROM shop_events e WHERE e.id = %s",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return EventState(*row)
