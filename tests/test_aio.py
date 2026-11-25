"""The asyncio backend on its own: plain ``async def`` calls, no HTTP, no database.

Each test drives it with ``asyncio.run``, so no async test plugin is needed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import racekit
from racekit import RoundResult


def test_every_client_runs_once_per_round_and_overlaps() -> None:
    active = most = 0
    seen: list[tuple[int, int]] = []
    rounds = {"n": 0}

    async def call(i: int) -> int:
        nonlocal active, most
        seen.append((rounds["n"], i))
        active += 1
        most = max(most, active)
        await asyncio.sleep(0.02)
        active -= 1
        return i * 2

    def reset() -> None:
        rounds["n"] += 1

    result = asyncio.run(racekit.arun(call, clients=6, rounds=3, reset=reset))
    assert result.rounds_run == 3
    assert sorted(seen) == [(r, i) for r in (1, 2, 3) for i in range(6)]
    assert most == 6
    assert [c.value for c in result.rounds[0].calls] == [0, 2, 4, 6, 8, 10]
    assert all(r.spread_ms >= 0 for r in result.rounds)


def test_prepare_reset_and_check_may_be_async() -> None:
    log: list[str] = []

    async def prepare(i: int) -> str:
        return f"conn-{i}"

    async def reset() -> None:
        log.append("reset")

    async def check(this: RoundResult) -> bool:
        log.append(f"check {this.number}")
        return this.number != 2

    async def call(i: int, state: str) -> str:
        return state

    result = asyncio.run(
        racekit.arun(call, clients=2, rounds=2, prepare=prepare, reset=reset, check=check)
    )
    assert log == ["reset", "check 1", "reset", "check 2"]
    assert [c.value for c in result.rounds[0].calls] == ["conn-0", "conn-1"]
    assert [r.violated for r in result.rounds] == [False, True]


def test_errors_are_recorded_and_assertions_in_check_are_violations() -> None:
    async def call(i: int) -> None:
        if i == 0:
            raise ConnectionError("refused")

    def check() -> None:
        sold, seats = 3, 2
        assert sold <= seats, "invariant broken"

    result = asyncio.run(racekit.arun(call, clients=3, check=check))
    first = result.rounds[0]
    assert first.errors == {"ConnectionError": 1}
    assert first.violated
    # pytest rewrites asserts in test files, so it appends its own explanation.
    assert (first.check_message or "").startswith("invariant broken")


def test_a_hung_call_is_cancelled_and_times_out_the_round() -> None:
    cancelled: list[int] = []

    async def call(i: int) -> None:
        if i == 1:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(i)
                raise

    with pytest.raises(racekit.RoundTimeout, match=r"clients \[1\]\); they were cancelled"):
        asyncio.run(racekit.arun(call, clients=3, round_timeout=0.2))
    assert cancelled == [1]


def test_rng_is_per_task_and_fixed_by_the_seed() -> None:
    async def call(i: int) -> float:
        await asyncio.sleep(0)  # let the other tasks run in between
        return racekit.rng().random()

    def values(seed: int) -> list[Any]:
        result = asyncio.run(racekit.arun(call, clients=4, rounds=2, seed=seed))
        return [[c.value for c in r.calls] for r in result.rounds]

    assert values(3) == values(3)
    assert values(3) != values(4)
    flat = [v for rnd in values(3) for v in rnd]
    assert len(set(flat)) == len(flat)


def test_thread_and_task_give_the_same_numbers_for_the_same_seed() -> None:
    async def acall(i: int) -> float:
        return racekit.rng().random()

    threaded = racekit.run(lambda i: racekit.rng().random(), clients=3, seed=8)
    tasked = asyncio.run(racekit.arun(acall, clients=3, seed=8))
    assert [c.value for c in threaded.rounds[0].calls] == [c.value for c in tasked.rounds[0].calls]


def test_a_plain_function_is_refused() -> None:
    with pytest.raises(TypeError, match="needs an async def"):
        asyncio.run(racekit.arun(lambda i: None, clients=2))  # type: ignore[arg-type,return-value]


def test_failing_prepare_raises_before_any_round() -> None:
    async def prepare(i: int) -> None:
        if i == 1:
            raise OSError("no server")

    async def call(i: int, state: None) -> None:
        raise AssertionError("must not run")

    with pytest.raises(racekit.PrepareError, match="client 1"):
        asyncio.run(racekit.arun(call, clients=2, prepare=prepare))
