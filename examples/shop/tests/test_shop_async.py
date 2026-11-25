"""The asyncio backend against the real shop: same race, ``httpx.AsyncClient``, one event loop.

``naive`` must still be caught; ``atomic_update`` must still never be accused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from harness import async_reserve_race, serve


@pytest.fixture(scope="module")
def shop(request: pytest.FixtureRequest, pg_dsn: str) -> Iterator[tuple[str, str]]:
    strategy: str = request.param
    with serve(pg_dsn, strategy) as url:
        yield strategy, url


@pytest.mark.parametrize("shop", ["naive"], indirect=True)
def test_async_backend_catches_naive(shop: tuple[str, str], pg_dsn: str) -> None:
    result = asyncio.run(async_reserve_race(shop[1], pg_dsn))
    print(f"\nasync naive: {result.violations} of {result.rounds_run} rounds oversold")
    assert result.violations > 0, result.report()


@pytest.mark.parametrize("shop", ["atomic_update"], indirect=True)
def test_async_backend_does_not_accuse_atomic_update(shop: tuple[str, str], pg_dsn: str) -> None:
    result = asyncio.run(async_reserve_race(shop[1], pg_dsn))
    assert result.violations == 0, result.report()
    assert all(not r.errors for r in result.rounds)
