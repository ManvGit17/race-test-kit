"""The runner against a live HTTP service: a PostgreSQL counter with and without a lost update.

``test_naive_counter_loses_updates`` is the Phase 1 reference test: the naive counter must stay
broken, and this test proves the runner still catches it. ``bench/phase1_detection.py`` runs it
100 times to measure how often.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

import racekit

COUNTER_APP = Path(__file__).parent / "apps" / "counter.py"
CLIENTS = 10
ROUNDS = 10

# httpx builds an SSL context per client unless given one: about 140 ms each on Windows,
# measured in the prior-art lab.
_SSL = ssl.create_default_context()


def _start(dsn: str, mode: str) -> Iterator[str]:
    proc = subprocess.Popen(
        [sys.executable, str(COUNTER_APP), "--dsn", dsn, "--mode", mode, "--key", mode],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        port = proc.stdout.readline().strip()
        if not port:
            pytest.fail(f"the {mode} counter app did not start (exit code {proc.poll()})")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.kill()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def naive_url(pg_dsn: str) -> Iterator[str]:
    yield from _start(pg_dsn, "naive")


@pytest.fixture(scope="session")
def atomic_url(pg_dsn: str) -> Iterator[str]:
    yield from _start(pg_dsn, "atomic")


def increment_race(url: str) -> racekit.RunResult:
    """CLIENTS increments per round; the counter must end at CLIENTS."""
    admin = httpx.Client(base_url=url, verify=_SSL)
    opened: list[httpx.Client] = []

    def prepare(i: int) -> httpx.Client:
        client = httpx.Client(base_url=url, verify=_SSL, timeout=30)
        client.get("/health")  # open the connection before the race
        opened.append(client)
        return client

    def check() -> None:
        value = admin.get("/value").json()["value"]
        assert value == CLIENTS, f"{CLIENTS} increments, counter is {value}"

    try:
        result = racekit.run(
            lambda i, client: client.post("/incr"),
            clients=CLIENTS,
            rounds=ROUNDS,
            prepare=prepare,
            reset=lambda: admin.post("/reset"),
            check=check,
        )
    finally:
        for client in [admin, *opened]:
            client.close()
    _write_bench_record(result)
    return result


def _write_bench_record(result: racekit.RunResult) -> None:
    """For bench/phase1_detection.py: the per-round outcome of this test run."""
    out = os.environ.get("RACEKIT_BENCH_OUT")
    if out:
        record = {
            "seed": result.seed,
            "clients": result.clients,
            "rounds": result.rounds_run,
            "violations": result.violations,
            "spread_ms": [round(r.spread_ms, 3) for r in result.rounds],
            "errors": sum(sum(r.errors.values()) for r in result.rounds),
        }
        Path(out).write_text(json.dumps(record), encoding="utf-8")


def test_naive_counter_loses_updates(naive_url: str) -> None:
    result = increment_race(naive_url)
    assert result.violations > 0, result.summary()


def test_atomic_counter_never_loses_an_update(atomic_url: str) -> None:
    result = increment_race(atomic_url)
    assert result.violations == 0, result.summary()
    assert all(r.statuses == {200: CLIENTS} for r in result.rounds)


def test_failure_summary_shows_the_lost_updates(naive_url: str) -> None:
    result = increment_race(naive_url)
    text = result.summary()
    assert f"{CLIENTS} clients" in text
    assert f"{CLIENTS} increments, counter is" in text
    assert "statuses 200 x10" in text
