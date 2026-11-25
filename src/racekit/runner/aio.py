"""The asyncio backend: ``await racekit.arun(...)``, the same rounds as ``racekit.run``.

One event loop, one task per client per round. Each round:

1. every task counts itself as parked and waits on one ``asyncio.Event`` (the gate);
2. when the last one has parked, the coordinator sets the event and the loop resumes them
   one after another, each noting the time and starting its call;
3. the coordinator waits for all of them, with a timeout.

Differences from the thread backend, all from asyncio itself: tasks are cheap, so many clients
cost little; the loop resumes tasks in one thread, so there is no GIL contention between them;
and a hung call can be *cancelled*, which a thread cannot.

``prepare``, ``reset`` and ``check`` may be plain or ``async`` functions.
"""

from __future__ import annotations

import asyncio
import inspect
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from racekit.invariants.result import RoundResult, RunResult
from racekit.runner import rng
from racekit.runner.capture import CallRecord
from racekit.runner.rounds import wants_round
from racekit.runner.threads import PrepareError, RoundTimeout


async def arun(
    call: Callable[..., Awaitable[Any]],
    *,
    clients: int,
    rounds: int = 1,
    prepare: Callable[[int], Any] | None = None,
    reset: Callable[[], object] | None = None,
    check: Callable[..., object] | None = None,
    seed: int | None = None,
    round_timeout: float = 30.0,
) -> RunResult:
    """Like ``racekit.run``, with ``call`` an ``async def`` run as tasks on the current loop."""
    if clients < 2:
        raise ValueError("clients must be at least 2: one client cannot race")
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    if not inspect.iscoroutinefunction(call):
        raise TypeError("arun needs an async def call; use racekit.run for plain functions")
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)

    states: list[Any] = []
    if prepare is not None:
        for i in range(clients):
            try:
                states.append(await _maybe_await(prepare(i)))
            except Exception as exc:
                raise PrepareError(f"prepare failed for client {i}: {exc!r}") from exc

    result = RunResult(seed=seed, clients=clients)
    for number in range(1, rounds + 1):
        if reset is not None:
            await _maybe_await(reset())
        records = await _round(call, clients, states, seed, number, round_timeout)
        this = RoundResult(number, records)
        this.violated, this.check_message = await _check(check, this)
        result.rounds.append(this)
    return result


async def _round(
    call: Callable[..., Awaitable[Any]],
    clients: int,
    states: list[Any],
    seed: int,
    number: int,
    timeout: float,
) -> list[CallRecord]:
    records = [CallRecord(i) for i in range(clients)]
    gate = asyncio.Event()
    everyone_parked = asyncio.Event()
    parked = 0

    async def worker(index: int) -> None:
        nonlocal parked
        parked += 1
        if parked == clients:
            everyone_parked.set()
        await gate.wait()
        record = records[index]
        record.released = time.perf_counter()
        rng.set_current(rng.for_call(seed, number, index))  # this task's own context
        try:
            record.value = await (call(index, states[index]) if states else call(index))
        # Exception, not BaseException: cancellation (a timed-out round) must propagate.
        except Exception as exc:
            record.error = exc
        finally:
            record.ended = time.perf_counter()

    # The loop resumes waiters in the order they were created: shuffle it, as the threads do.
    order = rng.start_order(seed, number, clients)
    by_client = {i: asyncio.create_task(worker(i)) for i in order}
    tasks = [by_client[i] for i in range(clients)]
    await everyone_parked.wait()
    gate.set()
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        stuck = [i for i, task in enumerate(tasks) if task in pending]
        raise RoundTimeout(
            f"round {number}: {len(pending)} call(s) still running after {timeout:g} s"
            f" (clients {stuck[:10]}); they were cancelled"
        )
    return records


async def _check(check: Callable[..., object] | None, this: RoundResult) -> tuple[bool, str | None]:
    if check is None:
        return False, None
    try:
        outcome = await _maybe_await(check(this) if wants_round(check) else check())
    except AssertionError as exc:
        return True, str(exc) or "AssertionError"
    if outcome is False:
        return True, "check returned False"
    return False, None


async def _maybe_await(value: object) -> object:
    return await value if inspect.isawaitable(value) else value
