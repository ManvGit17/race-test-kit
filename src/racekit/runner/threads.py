"""The thread backend: one long-lived worker thread per client.

Workers are started once and reused every round, so thread creation never falls inside the
race window. Each round:

1. the coordinator hands out fresh ``CallRecord``s and arrives at the gate;
2. every worker leaves the gate, notes the time and makes its call;
3. every worker arrives at the "done" barrier; the coordinator waits there too, with a timeout.

A call that raises is recorded and the worker carries on to the "done" barrier, so one
failure never strands the others. A call that hangs cannot be stopped (Python threads cannot
be killed), so the round times out and the run ends with an error naming the stuck clients.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from racekit.runner import rng
from racekit.runner.capture import CallRecord
from racekit.runner.gate import Gate


class PrepareError(RuntimeError):
    """``prepare`` raised for at least one client, so no round was run."""


class RoundTimeout(RuntimeError):
    """At least one call did not finish within ``round_timeout``."""


class WorkerPool:
    def __init__(
        self,
        call: Callable[..., Any],
        clients: int,
        prepare: Callable[[int], Any] | None,
        seed: int,
        round_timeout: float,
    ) -> None:
        self._call = call
        self._clients = clients
        self._prepare = prepare
        self._seed = seed
        self._timeout = round_timeout
        self._ready = threading.Barrier(clients + 1)
        self._gate = Gate(clients)
        self._done = threading.Barrier(clients + 1)
        self._prepare_errors: dict[int, BaseException] = {}
        self._records: list[CallRecord] = []
        self._round = 0
        self._threads = [
            threading.Thread(target=self._work, args=(i,), name=f"racekit-{i}", daemon=True)
            for i in range(clients)
        ]

    # -- coordinator side ----------------------------------------------------------------

    def start(self) -> None:
        """Start the workers and wait until each has run ``prepare``."""
        for thread in self._threads:
            thread.start()
        try:
            self._ready.wait(self._timeout)
        except threading.BrokenBarrierError:
            self.close()
            raise PrepareError(
                f"prepare did not finish for every client within {self._timeout:g} s"
            ) from None
        if self._prepare_errors:
            self.close()
            first = min(self._prepare_errors)
            raise PrepareError(
                f"prepare failed for {len(self._prepare_errors)} of {self._clients} clients;"
                f" client {first}: {self._prepare_errors[first]!r}"
            ) from self._prepare_errors[first]

    def run_round(self, number: int) -> list[CallRecord]:
        self._round = number
        self._records = [CallRecord(i) for i in range(self._clients)]
        try:
            self._gate.wait(self._timeout)
            self._done.wait(self._timeout)
        except threading.BrokenBarrierError:
            stuck = [r.index for r in self._records if r.ended == 0.0]
            self.close()
            raise RoundTimeout(
                f"round {number}: {len(stuck)} call(s) still running after"
                f" {self._timeout:g} s (clients {stuck[:10]})"
            ) from None
        return self._records

    def close(self) -> None:
        """Release every worker that is waiting, so it can exit."""
        self._gate.abort()
        self._done.abort()
        self._ready.abort()

    # -- worker side ---------------------------------------------------------------------

    def _work(self, index: int) -> None:
        state: Any = None
        if self._prepare is not None:
            try:
                state = self._prepare(index)
            except BaseException as exc:  # reported by start(); must not strand the others
                self._prepare_errors[index] = exc
        try:
            self._ready.wait()
        except threading.BrokenBarrierError:
            return
        while True:
            try:
                released = self._gate.wait()
            except threading.BrokenBarrierError:
                return
            record = self._records[index]
            record.released = released
            rng.set_current(rng.for_call(self._seed, self._round, index))
            try:
                if self._prepare is None:
                    record.value = self._call(index)
                else:
                    record.value = self._call(index, state)
            except BaseException as exc:  # recorded, never raised: the others must not hang
                record.error = exc
            finally:
                record.ended = time.perf_counter()
                rng.set_current(None)
            try:
                self._done.wait()
            except threading.BrokenBarrierError:
                return
