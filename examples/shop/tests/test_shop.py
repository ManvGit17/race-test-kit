"""The demo shop under racekit: 50 students, 10 seats, 20 rounds, per strategy.

``test_naive_oversells`` is the guard the plan asks for: ``naive`` is broken on purpose, and
this test fails if racekit stops catching it. The three safe strategies must never oversell.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import psycopg
import pytest
import shopdb
from harness import EVENT, ShopRace, reserve_race, serve

CLIENTS = 50
SEATS = 10
ROUNDS = 20
SAFE = ["row_lock", "atomic_update", "skip_locked"]


@pytest.fixture(scope="module")
def shop(request: pytest.FixtureRequest, pg_dsn: str) -> Iterator[tuple[str, str]]:
    """The shop running the strategy the test asks for (``indirect`` parametrize).

    Module scope, and pytest orders the tests by parameter, so each strategy's server starts
    once and only one runs at a time.
    """
    strategy: str = request.param
    with serve(pg_dsn, strategy) as url:
        yield strategy, url


def _race(shop: tuple[str, str], dsn: str) -> ShopRace:
    strategy, url = shop
    race = reserve_race(url, dsn, strategy, clients=CLIENTS, seats=SEATS, rounds=ROUNDS)
    print(
        f"\n{strategy}: {race.result.violations} of {race.result.rounds_run} rounds oversold;"
        f" sold out in {race.rounds_sold_out}; sold per round {race.sold}"
    )
    return race


@pytest.mark.parametrize("shop", ["naive"], indirect=True)
def test_naive_oversells(shop: tuple[str, str], pg_dsn: str) -> None:
    race = _race(shop, pg_dsn)
    assert race.result.violations > 0, race.result.summary()


@pytest.mark.parametrize("shop", SAFE, indirect=True)
def test_safe_strategy_never_oversells(shop: tuple[str, str], pg_dsn: str) -> None:
    race = _race(shop, pg_dsn)
    assert race.result.violations == 0, race.result.summary()
    for rnd in race.result.rounds:
        assert not rnd.errors, rnd.errors
        assert set(rnd.statuses) <= {201, 409, 503}, rnd.statuses
    if shop[0] in ("row_lock", "atomic_update"):
        # 50 students want 10 seats: these two must sell every one of them.
        assert race.rounds_sold_out == ROUNDS, race.sold


@pytest.mark.parametrize("shop", ["naive", *SAFE], indirect=True)
def test_duplicate_and_unknown_event(shop: tuple[str, str], pg_dsn: str) -> None:
    """Plain behaviour, one request at a time: the same for every strategy.

    Two seats, so a repeat request comes while a seat is still free. (With one seat taken
    and none left, naive and row_lock answer "full" before they look for the student: they
    count first. That is the order festrush uses too.)
    """
    url = shop[1]
    with psycopg.connect(pg_dsn, autocommit=True) as db:
        shopdb.reset_event(db, EVENT, 2)
    with httpx.Client(base_url=url) as client:
        assert client.post(f"/events/{EVENT}/reserve", json={"student": 1}).status_code == 201
        again = client.post(f"/events/{EVENT}/reserve", json={"student": 1})
        assert (again.status_code, again.json()) == (409, {"result": "already"})
        assert client.post(f"/events/{EVENT}/reserve", json={"student": 2}).status_code == 201
        full = client.post(f"/events/{EVENT}/reserve", json={"student": 3})
        assert (full.status_code, full.json()) == (409, {"result": "full"})
        assert client.post("/events/999/reserve", json={"student": 1}).status_code == 404
        assert client.get(f"/events/{EVENT}").json() == {"capacity": 2, "taken": 2}
