"""Ready-made races, each a thin layer over ``racekit.run``.

- ``duplicate``: the same request several times at once (retries, double clicks).
- ``lost_update``: many read-modify-write updates at once; checks none went missing.
- ``interleave``: different named steps at once (pay against cancel).

Rounds, reset, seed, spread and the report work exactly as with ``racekit.run``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from racekit.invariants.result import RoundResult, RunResult
from racekit.runner.capture import CallRecord
from racekit.runner.rounds import run


def duplicate(
    call: Callable[..., Any],
    *,
    copies: int = 5,
    rounds: int = 1,
    prepare: Callable[[int], Any] | None = None,
    reset: Callable[[], object] | None = None,
    check: Callable[..., object] | None = None,
    seed: int | None = None,
    round_timeout: float = 30.0,
) -> RunResult:
    """Send the same request ``copies`` times at once, ``rounds`` times.

    ``call()`` takes no client index: every copy is the same request. With ``prepare`` it is
    ``call(state)``, each copy with its own state (its own connection, say).
    """
    if prepare is None:
        return run(
            lambda i: call(),
            clients=copies,
            rounds=rounds,
            reset=reset,
            check=check,
            seed=seed,
            round_timeout=round_timeout,
        )
    return run(
        lambda i, state: call(state),
        clients=copies,
        rounds=rounds,
        prepare=prepare,
        reset=reset,
        check=check,
        seed=seed,
        round_timeout=round_timeout,
    )


def acknowledged(call: CallRecord) -> bool:
    """A call the service said yes to: it returned, with a 2xx status or no status at all."""
    return call.ok and (call.status is None or 200 <= call.status < 300)


def lost_update(
    apply: Callable[..., Any],
    *,
    read: Callable[[], float],
    clients: int,
    delta: float = 1,
    rounds: int = 1,
    prepare: Callable[[int], Any] | None = None,
    reset: Callable[[], object] | None = None,
    seed: int | None = None,
    round_timeout: float = 30.0,
) -> RunResult:
    """``clients`` updates at once, each adding ``delta``; check that none went missing.

    Before each round (after ``reset``), ``read()`` gives the starting value. After it, the
    value must equal the start plus ``delta`` for every *acknowledged* update (2xx, or no
    exception for non-HTTP calls). Counting only acknowledged updates means a service that
    correctly refuses some updates under contention is not accused of losing them.
    """
    start: dict[str, float] = {}

    def reset_and_read() -> None:
        if reset is not None:
            reset()
        start["value"] = read()

    def check(this: RoundResult) -> None:
        said_yes = sum(acknowledged(c) for c in this.calls)
        expected = start["value"] + delta * said_yes
        actual = read()
        if actual != expected:  # not `assert`: see racekit/invariants/checks.py
            raise AssertionError(
                f"{said_yes} updates acknowledged: expected {expected:g}, found {actual:g}"
                f" ({(expected - actual) / delta:g} updates lost)"
            )

    return run(
        apply,
        clients=clients,
        rounds=rounds,
        prepare=prepare,
        reset=reset_and_read,
        check=check,
        seed=seed,
        round_timeout=round_timeout,
    )


def interleave(
    steps: Mapping[str, Callable[..., Any]],
    *,
    copies: int = 1,
    rounds: int = 1,
    prepare: Callable[[int], Any] | None = None,
    reset: Callable[[], object] | None = None,
    check: Callable[..., object] | None = None,
    seed: int | None = None,
    round_timeout: float = 30.0,
) -> RunResult:
    """Release different named steps together: ``copies`` of each, ``rounds`` times.

    Each step is called with its copy number ``k`` (0 to ``copies - 1``), so copy ``k`` of
    every step can work on the same thing, for example order ``k``. With ``prepare`` the
    call is ``step(k, state)``. The result's ``steps`` names the step each client ran, and the
    report shows statuses per step.
    """
    if len(steps) < 2:
        raise ValueError("interleave needs at least two steps")
    if copies < 1:
        raise ValueError("copies must be at least 1")
    names = list(steps)
    # Client i runs step names[i % len(names)] on copy i // len(names): pay 0, cancel 0, ...
    plan = [(names[i % len(names)], i // len(names)) for i in range(len(names) * copies)]

    def call(i: int, *state: Any) -> Any:
        name, k = plan[i]
        return steps[name](k, *state)

    result = run(
        call,
        clients=len(plan),
        rounds=rounds,
        prepare=prepare,
        reset=reset,
        check=check,
        seed=seed,
        round_timeout=round_timeout,
    )
    result.steps = [name for name, _ in plan]
    return result


__all__ = ["acknowledged", "duplicate", "interleave", "lost_update"]
