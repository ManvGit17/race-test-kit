"""The starting gate: park every worker, then release them together.

A ``threading.Barrier`` with one party per worker plus one for the coordinator. Every worker
is already blocked inside ``wait()`` before the coordinator arrives, so the release costs one
wake-up per thread rather than one thread start per thread.

The release is not instant: Python wakes the threads one after another, and each needs the
GIL to run. ``spread_ms`` measures how far apart they really left, from each worker's own
clock reading right after ``wait()`` returns.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable


class Gate:
    def __init__(self, workers: int) -> None:
        self._barrier = threading.Barrier(workers + 1)

    def wait(self, timeout: float | None = None) -> float:
        """Block until every party has arrived; return the instant this caller left.

        Raises ``threading.BrokenBarrierError`` if the gate was aborted or timed out.
        """
        self._barrier.wait(timeout)
        return time.perf_counter()

    def abort(self) -> None:
        """Release everyone still waiting with ``BrokenBarrierError``. Used to shut down."""
        self._barrier.abort()


def spread_ms(released: Iterable[float]) -> float:
    """Milliseconds between the first and the last worker leaving the gate."""
    times = list(released)
    if len(times) < 2:
        return 0.0
    return (max(times) - min(times)) * 1000
