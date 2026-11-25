"""``Race``: what the pytest fixture and ``racekit run`` hand to a scenario.

It has the same methods as the library (``run``, ``duplicate``, ``lost_update``,
``interleave``, ``arun``) with two additions:

- **defaults**: ``rounds`` and ``seed`` are filled in when a call does not pass them. The
  fixture takes them from the ``@pytest.mark.race`` marker, then from ``--race-rounds`` and
  ``--race-seed``; the CLI from its ``--rounds`` and ``--seed``. An argument written in the
  call always wins.
- **memory**: every result is kept, so a failing test or a CLI run can show all the reports.

A scenario written as ``def race_x(race): ...`` runs unchanged under pytest (as a test taking
the ``race`` fixture) and under ``racekit run``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from racekit.invariants.result import RunResult
from racekit.runner.aio import arun as _arun
from racekit.runner.rounds import run as _run
from racekit.scenarios import duplicate as _duplicate
from racekit.scenarios import interleave as _interleave
from racekit.scenarios import lost_update as _lost_update


class Race:
    def __init__(self, rounds: int | None = None, seed: int | None = None) -> None:
        self.rounds = rounds
        self.seed = seed
        #: Every run so far, as (what ran, its result), in order.
        self.results: list[tuple[str, RunResult]] = []

    def _defaults(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if kwargs.get("rounds") is None and self.rounds is not None:
            kwargs["rounds"] = self.rounds
        if kwargs.get("seed") is None and self.seed is not None:
            kwargs["seed"] = self.seed
        return kwargs

    def _keep(self, name: str, result: RunResult) -> RunResult:
        self.results.append((name, result))
        return result

    def run(self, call: Callable[..., Any], **kwargs: Any) -> RunResult:
        """``racekit.run`` with this race's defaults. Same arguments."""
        return self._keep("run", _run(call, **self._defaults(kwargs)))

    def duplicate(self, call: Callable[..., Any], **kwargs: Any) -> RunResult:
        """``racekit.duplicate`` with this race's defaults. Same arguments."""
        return self._keep("duplicate", _duplicate(call, **self._defaults(kwargs)))

    def lost_update(self, apply: Callable[..., Any], **kwargs: Any) -> RunResult:
        """``racekit.lost_update`` with this race's defaults. Same arguments."""
        return self._keep("lost_update", _lost_update(apply, **self._defaults(kwargs)))

    def interleave(self, steps: dict[str, Callable[..., Any]], **kwargs: Any) -> RunResult:
        """``racekit.interleave`` with this race's defaults. Same arguments."""
        return self._keep("interleave", _interleave(steps, **self._defaults(kwargs)))

    async def arun(self, call: Callable[..., Awaitable[Any]], **kwargs: Any) -> RunResult:
        """``racekit.arun`` with this race's defaults. Same arguments."""
        return self._keep("arun", await _arun(call, **self._defaults(kwargs)))

    def report(self) -> str:
        """Every run's report, numbered, in the order they ran."""
        if not self.results:
            return "racekit: no runs"
        return "\n\n".join(
            f"[{n}] {name}\n{result.report()}"
            for n, (name, result) in enumerate(self.results, start=1)
        )
