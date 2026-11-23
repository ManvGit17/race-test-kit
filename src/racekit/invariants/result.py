"""What a run returns: one ``RoundResult`` per round, gathered in a ``RunResult``."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from racekit.runner.capture import CallRecord
from racekit.runner.gate import spread_ms

#: How many violating rounds ``report()`` shows in full.
REPORT_ROUNDS = 3


@dataclass
class RoundResult:
    number: int
    calls: list[CallRecord]
    violated: bool = False
    #: Why the check failed: the AssertionError's message, or "check returned False".
    check_message: str | None = None

    @property
    def spread_ms(self) -> float:
        """How far apart the workers left the gate in this round."""
        return spread_ms(call.released for call in self.calls)

    @property
    def statuses(self) -> Counter[int | None]:
        """How many calls returned each status (``None`` when there was no status)."""
        return _statuses(self.calls)

    @property
    def errors(self) -> Counter[str]:
        """How many calls raised each exception type."""
        return Counter(type(call.error).__name__ for call in self.calls if call.error)


@dataclass
class RunResult:
    seed: int
    clients: int
    rounds: list[RoundResult] = field(default_factory=list)
    #: For ``interleave``: the step each client ran, by client index.
    steps: list[str] | None = None

    @property
    def rounds_run(self) -> int:
        return len(self.rounds)

    @property
    def violations(self) -> int:
        """Rounds in which the invariant check failed."""
        return sum(r.violated for r in self.rounds)

    @property
    def violation_rate(self) -> float:
        return self.violations / self.rounds_run if self.rounds else 0.0

    def summary(self) -> str:
        """A few lines: rounds, violations, spread, the first violating round, the seed."""
        lines = [self._headline()]
        if self.rounds:
            lines.append(self._spread_line())
        failing = next((r for r in self.rounds if r.violated), None)
        if failing is not None:
            lines.append(
                f"first violating round ({failing.number}): statuses"
                f" {_mix(failing.statuses)}; errors {_mix(failing.errors)};"
                f" check: {failing.check_message}"
            )
        lines.append(self._seed_line())
        return "\n".join(lines)

    def report(self) -> str:
        """The full failure report, for an assertion message."""
        lines = [self._headline()]
        if not self.rounds:
            return "\n".join([*lines, self._seed_line()])
        calls = [c for r in self.rounds for c in r.calls]
        bad = [r for r in self.rounds if r.violated]
        lines.append(self._spread_line())
        latencies = sorted(c.latency_ms for c in calls)
        lines.append(
            f"latency: p50 {_percentile(latencies, 50):.1f} ms,"
            f" p95 {_percentile(latencies, 95):.1f} ms, max {latencies[-1]:.1f} ms"
        )
        lines.append(f"statuses, all rounds: {_mix(_statuses(calls))}")
        if bad:
            bad_calls = [c for r in bad for c in r.calls]
            lines.append(f"statuses, violating rounds: {_mix(_statuses(bad_calls))}")
        if self.steps is not None:
            for name in dict.fromkeys(self.steps):
                mine = [c for c in calls if self.steps[c.index] == name]
                lines.append(f"  step {name}: {_mix(_statuses(mine))}")
        errors = Counter(type(c.error).__name__ for c in calls if c.error)
        if errors:
            lines.append(f"errors, all rounds: {_mix(errors)}")
        if bad:
            lines.append(f"violating rounds (first {min(len(bad), REPORT_ROUNDS)} of {len(bad)}):")
            for r in bad[:REPORT_ROUNDS]:
                lines.append(
                    f"  round {r.number}: {r.check_message}; statuses {_mix(r.statuses)};"
                    f" spread {r.spread_ms:.1f} ms"
                )
                first = next((c for c in r.calls if c.error), None)
                if first is not None:
                    lines.append(f"    first error, client {first.index}: {first.error!r}")
        else:
            lines.append("no round violated the invariant")
        lines.append(self._seed_line())
        return "\n".join(lines)

    def _headline(self) -> str:
        return (
            f"racekit: {self.violations} of {self.rounds_run} rounds violated the invariant"
            f" ({self.violation_rate:.0%}), {self.clients} clients, seed {self.seed}"
        )

    def _spread_line(self) -> str:
        spreads = [r.spread_ms for r in self.rounds]
        return (
            f"start spread: median {statistics.median(spreads):.1f} ms, worst {max(spreads):.1f} ms"
        )

    def _seed_line(self) -> str:
        return f"rerun with seed={self.seed} to repeat the same inputs"


def _statuses(calls: Iterable[CallRecord]) -> Counter[int | None]:
    return Counter(call.status for call in calls if call.ok)


def _mix(counts: Counter[int | None] | Counter[str]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{k} x{n}" for k, n in sorted(counts.items(), key=lambda kv: str(kv[0])))


def _percentile(ordered: list[float], pct: int) -> float:
    """Nearest-rank percentile of an already sorted list."""
    return ordered[max(0, -(-pct * len(ordered) // 100) - 1)]
