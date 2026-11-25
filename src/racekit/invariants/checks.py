"""Ready-made checks that look at a round's responses. No database needed.

Each returns a ``check(round)`` for ``racekit.run`` and the scenarios.

They raise ``AssertionError`` explicitly instead of using ``assert``: pytest rewrites asserts in
installed plugins' packages and would append its own explanation to these messages.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from racekit.invariants.result import RoundResult


def at_most(status: int, n: int) -> Callable[[RoundResult], None]:
    """At most ``n`` calls in the round got ``status`` (for example one 201 per seat)."""

    def check(round: RoundResult) -> None:
        got = round.statuses[status]
        if got > n:
            raise AssertionError(f"{got} responses with status {status}, at most {n} allowed")

    return check


def same_response(key: Callable[[Any], object]) -> Callable[[RoundResult], None]:
    """Every successful call got the same answer, as extracted by ``key(value)``.

    For idempotency: ``same_response(lambda r: r.json()["charge"])`` fails when two copies
    of one request were given different charges. Calls that raised are left out, so are
    responses with a 4xx or 5xx status.
    """

    def check(round: RoundResult) -> None:
        answers = {
            repr(key(c.value)) for c in round.calls if c.ok and (c.status is None or c.status < 400)
        }
        if len(answers) > 1:
            raise AssertionError(f"{len(answers)} different answers: {sorted(answers)[:5]}")

    return check
