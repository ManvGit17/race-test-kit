"""``racekit.rng()``: a random generator for the current call, fixed by the run's seed.

Each call gets ``random.Random(f"{seed}:{round}:{index}")``. String seeds are hashed with
SHA-512, so the same seed, round and client always give the same numbers, on any machine and
in any thread order. That makes a failing round's *inputs* reproducible. Its *timing* is not:
the operating system decides how threads are scheduled.
"""

from __future__ import annotations

import random
import threading

_current = threading.local()


def rng() -> random.Random:
    """The random generator of the call running in this thread.

    Only valid inside a function passed to ``racekit.run``; raises ``RuntimeError`` elsewhere.
    """
    generator: random.Random | None = getattr(_current, "rng", None)
    if generator is None:
        raise RuntimeError("racekit.rng() is only available inside a call made by racekit.run")
    return generator


def for_call(seed: int, round_number: int, index: int) -> random.Random:
    return random.Random(f"{seed}:{round_number}:{index}")


def set_current(generator: random.Random | None) -> None:
    _current.rng = generator
