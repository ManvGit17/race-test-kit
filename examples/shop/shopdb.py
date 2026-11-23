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


# -- payments, wallets and orders -----------------------------------------------------------


def reset_payments(conn: psycopg.Connection[Any]) -> None:
    """Forget every charge and idempotency key."""
    with conn.transaction():
        conn.execute("DELETE FROM shop_idempotency_keys")
        conn.execute("DELETE FROM shop_charges")


def charges_for_key(conn: psycopg.Connection[Any], key: str) -> int:
    row = conn.execute(
        "SELECT count(*) FROM shop_charges WHERE idempotency_key = %s", (key,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def reset_wallet(conn: psycopg.Connection[Any], wallet_id: int, balance: int) -> None:
    conn.execute(
        "INSERT INTO shop_wallets (id, balance) VALUES (%s, %s)"
        " ON CONFLICT (id) DO UPDATE SET balance = EXCLUDED.balance",
        (wallet_id, balance),
    )


def balance(conn: psycopg.Connection[Any], wallet_id: int) -> int:
    row = conn.execute("SELECT balance FROM shop_wallets WHERE id = %s", (wallet_id,)).fetchone()
    assert row is not None
    return int(row[0])


def reset_orders(conn: psycopg.Connection[Any], count: int, amount: int = 100) -> None:
    """Orders 1..count, all pending, with no charges."""
    with conn.transaction():
        conn.execute("DELETE FROM shop_charges WHERE idempotency_key IS NULL")
        conn.execute("DELETE FROM shop_orders")
        conn.execute(
            "INSERT INTO shop_orders (id, status, amount)"
            " SELECT n, 'pending', %s FROM generate_series(1, %s) n",
            (amount, count),
        )


@dataclass(frozen=True)
class OrderState:
    id: int
    status: str
    charges: int


def order_states(conn: psycopg.Connection[Any]) -> list[OrderState]:
    rows = conn.execute(
        "SELECT o.id, o.status, (SELECT count(*) FROM shop_charges c"
        "   WHERE c.order_id = o.id AND c.idempotency_key IS NULL)"
        " FROM shop_orders o ORDER BY o.id"
    ).fetchall()
    return [OrderState(int(r[0]), str(r[1]), int(r[2])) for r in rows]
