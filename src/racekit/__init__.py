"""Race Test Kit: release many requests from one starting gate and check invariants."""

from racekit.invariants.checks import at_most, same_response
from racekit.invariants.result import RoundResult, RunResult
from racekit.race import Race
from racekit.runner.aio import arun
from racekit.runner.capture import CallRecord
from racekit.runner.rng import rng
from racekit.runner.rounds import run
from racekit.runner.threads import PrepareError, RoundTimeout
from racekit.scenarios import duplicate, interleave, lost_update

__version__ = "0.1.1"

__all__ = [
    "CallRecord",
    "PrepareError",
    "Race",
    "RoundResult",
    "RoundTimeout",
    "RunResult",
    "__version__",
    "arun",
    "at_most",
    "duplicate",
    "interleave",
    "lost_update",
    "rng",
    "run",
    "same_response",
]
