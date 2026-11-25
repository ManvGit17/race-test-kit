"""``racekit.run``: the round loop around the worker pool."""

from __future__ import annotations

import inspect
import random
from collections.abc import Callable
from typing import Any

from racekit.invariants.result import RoundResult, RunResult
from racekit.runner.threads import WorkerPool


def run(
    call: Callable[..., Any],
    *,
    clients: int,
    rounds: int = 1,
    prepare: Callable[[int], Any] | None = None,
    reset: Callable[[], object] | None = None,
    check: Callable[..., object] | None = None,
    seed: int | None = None,
    round_timeout: float = 30.0,
) -> RunResult:
    """Release ``clients`` calls together, ``rounds`` times, checking the invariant after each.

    - ``call(i)`` is made once per client per round; ``i`` is the client index. With
      ``prepare``, it is ``call(i, state)`` where ``state = prepare(i)``.
    - ``prepare(i)`` runs once per client, in that client's worker thread, before the first
      round and outside the timed window: open connections here.
    - ``reset()`` runs before every round.
    - ``check()`` runs after every round. Returning ``False`` or raising ``AssertionError``
      marks the round as violated; any other return value (``None`` included, so a function
      that only asserts works) passes. Any other exception stops the run: a broken check is a
      bug, not a finding. A check that takes one argument, ``check(round)``, is given the
      round's ``RoundResult``, so it can look at the responses too.
    - ``seed`` fixes ``racekit.rng()`` for every call; a random one is chosen and recorded if
      not given.
    """
    if clients < 2:
        raise ValueError("clients must be at least 2: one client cannot race")
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)

    result = RunResult(seed=seed, clients=clients)
    pool = WorkerPool(call, clients, prepare, seed, round_timeout)
    pool.start()
    try:
        for number in range(1, rounds + 1):
            if reset is not None:
                reset()
            this = RoundResult(number, pool.run_round(number))
            this.violated, this.check_message = judge(check, this)
            result.rounds.append(this)
    finally:
        pool.close()
    return result


def judge(check: Callable[..., object] | None, this: RoundResult) -> tuple[bool, str | None]:
    """Run ``check`` on a finished round: (violated, why). Shared by every round loop."""
    if check is None:
        return False, None
    try:
        outcome = check(this) if wants_round(check) else check()
    except AssertionError as exc:
        return True, str(exc) or "AssertionError"
    if outcome is False:
        return True, "check returned False"
    return False, None


def wants_round(check: Callable[..., object]) -> bool:
    """Whether ``check`` has a required positional parameter, so it takes the round."""
    try:
        parameters = inspect.signature(check).parameters.values()
    except (TypeError, ValueError):  # some builtins have no signature: call them bare
        return False
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return any(p.kind in positional and p.default is p.empty for p in parameters)
