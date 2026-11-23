"""What a run returns: one ``RoundResult`` per round, gathered in a ``RunResult``."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from racekit.runner.capture import CallRecord
from racekit.runner.gate import spread_ms


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
        return Counter(call.status for call in self.calls if call.ok)

    @property
    def errors(self) -> Counter[str]:
        """How many calls raised each exception type."""
        return Counter(type(call.error).__name__ for call in self.calls if call.error)


@dataclass
class RunResult:
    seed: int
    clients: int
    rounds: list[RoundResult] = field(default_factory=list)

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
        """A few lines for a failure message. The full report comes in a later phase."""
        lines = [
            f"racekit: {self.violations} of {self.rounds_run} rounds violated the invariant"
            f" ({self.violation_rate:.0%}), {self.clients} clients, seed {self.seed}"
        ]
        if self.rounds:
            spreads = [r.spread_ms for r in self.rounds]
            lines.append(
                f"start spread: median {statistics.median(spreads):.1f} ms,"
                f" worst {max(spreads):.1f} ms"
            )
        failing = next((r for r in self.rounds if r.violated), None)
        if failing is not None:
            mix = ", ".join(f"{s} x{n}" for s, n in sorted(failing.statuses.items(), key=str))
            errors = ", ".join(f"{e} x{n}" for e, n in failing.errors.items()) or "none"
            lines.append(
                f"first violating round ({failing.number}): statuses {mix or 'none'};"
                f" errors {errors}; check: {failing.check_message}"
            )
        lines.append(f"rerun with seed={self.seed} to repeat the same inputs")
        return "\n".join(lines)
