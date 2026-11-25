"""Cashback against a top-up: a race load catches only about half the time, and pause points
catch every time.

The cashback (``SHOP_CASHBACK``) reads the balance, adds up last month's spending, and writes;
the top-up is the fixed, atomic one. With the pause point held, the top-up always lands between
the cashback's read and write.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from harness import cashback_race, forced_cashback_race, serve

PURCHASES = 1000  # in the wallet's history: makes adding up the spending take a moment
# By load alone the share of rounds that lose the top-up moved between about 15% and 75%
# from batch to batch while calibrating; 60 rounds keep "caught at least once" reliable.
LOAD_ROUNDS = 60
FORCED_ROUNDS = 10


@pytest.fixture(scope="module")
def shop(request: pytest.FixtureRequest, pg_dsn: str) -> Iterator[str]:
    mode, pause_points = request.param
    modes = {"wallet": "atomic", "cashback": mode}
    with serve(pg_dsn, modes=modes, pause_points=pause_points) as url:
        yield url


broken_load = pytest.mark.parametrize("shop", [("read_modify_write", False)], indirect=True)
broken_paused = pytest.mark.parametrize("shop", [("read_modify_write", True)], indirect=True)
fixed_load = pytest.mark.parametrize("shop", [("atomic", False)], indirect=True)
fixed_paused = pytest.mark.parametrize("shop", [("atomic", True)], indirect=True)


@broken_load
def test_load_catches_the_lost_top_up_in_some_rounds(shop: str, pg_dsn: str) -> None:
    result = cashback_race(shop, pg_dsn, purchases=PURCHASES, rounds=LOAD_ROUNDS)
    print(f"\nload alone: {result.violations} of {result.rounds_run} rounds lost the top-up")
    assert result.violations > 0, result.report()


@broken_paused
def test_pause_point_catches_it_every_round(shop: str, pg_dsn: str) -> None:
    result = forced_cashback_race(shop, pg_dsn, purchases=PURCHASES, rounds=FORCED_ROUNDS)
    assert result.violations == FORCED_ROUNDS, result.report()
    assert all("lost the top-up" in (r.check_message or "") for r in result.rounds)


@fixed_load
def test_atomic_cashback_survives_load(shop: str, pg_dsn: str) -> None:
    result = cashback_race(shop, pg_dsn, purchases=PURCHASES, rounds=LOAD_ROUNDS)
    assert result.violations == 0, result.report()


@fixed_paused
def test_atomic_cashback_survives_the_forced_order(shop: str, pg_dsn: str) -> None:
    result = forced_cashback_race(shop, pg_dsn, purchases=PURCHASES, rounds=FORCED_ROUNDS)
    assert result.violations == 0, result.report()
