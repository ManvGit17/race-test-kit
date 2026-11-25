"""``racekit.pg.force``: run two steps in one exact order, every round, with a pause point.

Each round: ``reset()``; start ``first`` in a thread while the test holds the pause point
``at``; wait until ``first`` is blocked there; run ``then`` to completion; release; wait for
``first`` to finish; ``check``. The result is an ordinary ``RunResult`` (client 0 is ``first``,
client 1 is ``then``), so ``report()``, ``violations`` and the pytest plugin work as usual.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from racekit.invariants.result import RoundResult, RunResult
from racekit.pg.pause import PausePointNotReached, PausePoints
from racekit.runner.capture import CallRecord
from racekit.runner.rounds import judge


def _call(fn: Callable[[], Any], record: CallRecord) -> None:
    record.released = time.perf_counter()
    try:
        record.value = fn()
    except Exception as exc:
        record.error = exc
    finally:
        record.ended = time.perf_counter()


def force(
    first: Callable[[], Any],
    then: Callable[[], Any],
    *,
    at: str,
    dsn: str,
    rounds: int = 1,
    reset: Callable[[], object] | None = None,
    check: Callable[..., object] | None = None,
    timeout: float = 10.0,
    names: tuple[str, str] = ("first", "then"),
) -> RunResult:
    """``first`` pauses at ``at``; ``then`` runs meanwhile; ``first`` finishes; check.

    The app under test must have ``RACEKIT_PAUSE_POINTS=1`` and call
    ``racekit.pg.pause_point(conn, at)`` on ``first``'s code path.
    """
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    pauses = PausePoints(dsn)
    result = RunResult(seed=0, clients=2, steps=list(names))
    for number in range(1, rounds + 1):
        if reset is not None:
            reset()
        held_first, ran_then = CallRecord(0), CallRecord(1)
        worker = threading.Thread(target=_call, args=(first, held_first), daemon=True)
        reached = True
        with pauses.hold(at) as held:
            worker.start()
            try:
                held.wait_until_paused(timeout)
            except PausePointNotReached:
                reached = False
            else:
                _call(then, ran_then)
        worker.join(timeout)
        if not reached:
            raise PausePointNotReached(
                f"round {number}: {names[0]} never reached pause point {at!r};"
                " is RACEKIT_PAUSE_POINTS=1 set for the app?"
            )
        if worker.is_alive():
            raise RuntimeError(f"round {number}: {names[0]} did not finish after the release")
        this = RoundResult(number, [held_first, ran_then])
        this.violated, this.check_message = judge(check, this)
        result.rounds.append(this)
    return result
