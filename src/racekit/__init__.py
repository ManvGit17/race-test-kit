"""Race Test Kit: release many requests from one starting gate and check invariants."""

from racekit.invariants.result import RoundResult, RunResult
from racekit.runner.capture import CallRecord
from racekit.runner.rng import rng
from racekit.runner.rounds import run
from racekit.runner.threads import PrepareError, RoundTimeout

__version__ = "0.0.0"

__all__ = [
    "CallRecord",
    "PrepareError",
    "RoundResult",
    "RoundTimeout",
    "RunResult",
    "__version__",
    "rng",
    "run",
]
