"""``racekit.rng()``: a random generator for the current call, fixed by the run's seed.

Each call gets ``random.Random(f"{seed}:{round}:{index}")``. String seeds are hashed with
SHA-512, so the same seed, round and client always give the same numbers, on any machine and
in any thread order. That makes a failing round's *inputs* reproducible. Its *timing* is not:
the operating system decides how threads are scheduled.

The current generator lives in a ``ContextVar``: each worker thread has its own context, and
each asyncio task gets a copy of its creator's, so threads and tasks never see each other's.
"""

from __future__ import annotations

import random
from contextvars import ContextVar

_current: ContextVar[random.Random | None] = ContextVar("racekit_rng", default=None)


def rng() -> random.Random:
    """The random generator of the call running here (this thread or this task).

    Only valid inside a function passed to ``racekit.run`` or ``racekit.arun``; raises
    ``RuntimeError`` elsewhere.
    """
    generator = _current.get()
    if generator is None:
        raise RuntimeError(
            "racekit.rng() is only available inside a call made by racekit.run or racekit.arun"
        )
    return generator


def for_call(seed: int, round_number: int, index: int) -> random.Random:
    return random.Random(f"{seed}:{round_number}:{index}")


def start_order(seed: int, round_number: int, clients: int) -> list[int]:
    """A seeded shuffle of the clients, for the order they are started in this round.

    A barrier (or an event loop) releases its waiters in much the same order every round, so
    without this, client 0 would nearly always start first and a race that depends on who goes
    first would be caught either almost always or almost never.
    """
    return random.Random(f"{seed}:{round_number}:order").sample(range(clients), clients)


def set_current(generator: random.Random | None) -> None:
    _current.set(generator)
