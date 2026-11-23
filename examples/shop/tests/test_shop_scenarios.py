"""The three scenarios against the shop, each with its broken and its fixed version.

The broken versions are the guards: if racekit stops catching one, its test fails. The fixed
versions must never be accused.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import psycopg
import pytest
import shopdb
from harness import duplicate_payment_race, pay_cancel_race, serve, topup_race

ROUNDS = 20
COPIES = 5
CLIENTS = 20
ORDERS = 5

BUILDS = {
    "broken": {
        "payments": "check_then_insert",
        "wallet": "read_modify_write",
        "orders": "check_then_act",
    },
    "fixed": {"payments": "unique_key", "wallet": "atomic", "orders": "guarded_update"},
}


@pytest.fixture(scope="module")
def shop(request: pytest.FixtureRequest, pg_dsn: str) -> Iterator[str]:
    """The shop with every feature broken, or every feature fixed (``indirect`` parametrize)."""
    with serve(pg_dsn, modes=BUILDS[request.param]) as url:
        yield url


broken = pytest.mark.parametrize("shop", ["broken"], indirect=True)
fixed = pytest.mark.parametrize("shop", ["fixed"], indirect=True)


# -- duplicate: one payment, sent five times at once ----------------------------------------


@broken
def test_duplicate_payment_is_caught(shop: str, pg_dsn: str) -> None:
    result = duplicate_payment_race(shop, pg_dsn, copies=COPIES, rounds=ROUNDS)
    assert result.violations > 0, result.report()


@fixed
def test_idempotency_key_charges_once(shop: str, pg_dsn: str) -> None:
    result = duplicate_payment_race(shop, pg_dsn, copies=COPIES, rounds=ROUNDS)
    assert result.violations == 0, result.report()
    for rnd in result.rounds:
        assert rnd.statuses == {201: 1, 200: COPIES - 1}, rnd.statuses


# -- lost_update: twenty top-ups at once ----------------------------------------------------


@broken
def test_lost_top_up_is_caught(shop: str, pg_dsn: str) -> None:
    result = topup_race(shop, pg_dsn, clients=CLIENTS, rounds=ROUNDS)
    assert result.violations > 0, result.report()


@fixed
def test_atomic_top_up_loses_nothing(shop: str, pg_dsn: str) -> None:
    result = topup_race(shop, pg_dsn, clients=CLIENTS, rounds=ROUNDS)
    assert result.violations == 0, result.report()
    assert all(rnd.statuses == {200: CLIENTS} for rnd in result.rounds)


# -- interleave: pay against cancel on five orders at once ----------------------------------


@broken
def test_pay_and_cancel_both_succeeding_is_caught(shop: str, pg_dsn: str) -> None:
    result = pay_cancel_race(shop, pg_dsn, orders=ORDERS, rounds=ROUNDS)
    assert result.violations > 0, result.report()


@fixed
def test_guarded_update_lets_exactly_one_win(shop: str, pg_dsn: str) -> None:
    result = pay_cancel_race(shop, pg_dsn, orders=ORDERS, rounds=ROUNDS)
    assert result.violations == 0, result.report()
    for rnd in result.rounds:
        assert rnd.statuses == {200: ORDERS, 409: ORDERS}, rnd.statuses


# -- one request at a time ------------------------------------------------------------------


@pytest.mark.parametrize("shop", ["broken", "fixed"], indirect=True)
def test_plain_behaviour(shop: str, pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn, autocommit=True) as db:
        shopdb.reset_payments(db)
        shopdb.reset_wallet(db, 1, 5)
        shopdb.reset_orders(db, 1)
    with httpx.Client(base_url=shop) as client:
        no_key = client.post("/payments", json={"order": 1, "amount": 5})
        assert no_key.status_code == 400

        def pay() -> httpx.Response:
            body = {"order": 1, "amount": 5}
            return client.post("/payments", json=body, headers={"Idempotency-Key": "a"})

        first, again = pay(), pay()
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json() == again.json()

        assert client.post("/wallets/1/topup", json={"amount": 3}).json() == {"balance": 8}
        assert client.post("/wallets/9/topup", json={"amount": 3}).status_code == 404

        assert client.post("/orders/1/pay").json() == {"status": "paid"}
        assert client.post("/orders/1/cancel").status_code == 409
        assert client.post("/orders/9/pay").status_code == 404
