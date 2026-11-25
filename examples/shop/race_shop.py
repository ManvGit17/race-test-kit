"""Race scenarios for the demo shop, written once, run by pytest or by ``racekit run``.

Start a shop, then:

    SHOP_URL=http://127.0.0.1:8000 TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test \\
        uv run racekit run examples/shop/race_shop.py --rounds 20

Each function takes the ``race`` a pytest test would get as a fixture, so the same function is
also a valid body for a test. They assert what a correct shop guarantees: against the broken
versions they fail, which is what they are for. The asserts need no ``result.report()``
message: the pytest plugin and the CLI both print every run's report after a failure.
"""

from __future__ import annotations

import os
import ssl

import httpx
import psycopg
import shopdb

from racekit import Race

URL = os.environ.get("SHOP_URL", "http://127.0.0.1:8000")
DSN = os.environ.get("TEST_PG_DSN", "postgresql://test:test@127.0.0.1:15418/test")
SEATS = 10
_SSL = ssl.create_default_context()


def _client(i: int) -> httpx.Client:
    client = httpx.Client(base_url=URL, verify=_SSL, timeout=30)
    client.get("/health")  # connect before the race
    return client


def race_never_oversells(race: Race) -> None:
    """50 students, 10 seats: never more than 10 reservations."""
    with psycopg.connect(DSN, autocommit=True) as db:

        def sold_at_most_capacity() -> None:
            state = shopdb.state(db, 1)
            assert state is not None
            assert state.sold <= SEATS, f"oversold: {state.sold} reservations, {SEATS} seats"

        result = race.run(
            lambda i, client: client.post("/events/1/reserve", json={"student": i}),
            clients=50,
            prepare=_client,
            reset=lambda: shopdb.reset_event(db, 1, SEATS),
            check=sold_at_most_capacity,
        )
    assert result.violations == 0


def race_top_ups_all_count(race: Race) -> None:
    """20 top-ups at once: the balance grows by every acknowledged one."""
    with psycopg.connect(DSN, autocommit=True) as db:
        result = race.lost_update(
            lambda i, client: client.post("/wallets/1/topup", json={"amount": 10}),
            read=lambda: shopdb.balance(db, 1),
            clients=20,
            delta=10,
            prepare=_client,
            reset=lambda: shopdb.reset_wallet(db, 1, 0),
        )
    assert result.violations == 0
