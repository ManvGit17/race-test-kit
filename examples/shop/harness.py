"""Start the shop as a real server and race students at it. Used by the tests and the bench.

``serve()`` runs uvicorn in a subprocess, so the shop never shares the test's GIL, and waits
until it answers. ``reserve_race()`` is the scenario: ``clients`` students try to reserve one
of ``seats`` seats, all released together, ``rounds`` times, with the event reset in the
database before each round and the invariants checked in the database after.
"""

from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg
import shopdb

import racekit

HERE = Path(__file__).resolve().parent
EVENT = 1

# httpx builds an SSL context per client unless given one: about 140 ms each on Windows.
_SSL = ssl.create_default_context()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@contextmanager
def serve(dsn: str, strategy: str, timeout: float = 60.0) -> Iterator[str]:
    """Run the shop with ``strategy`` and yield its base URL."""
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--app-dir",
            str(HERE),
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env={**os.environ, "SHOP_DSN": dsn, "SHOP_STRATEGY": strategy},
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + timeout
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"the {strategy} shop exited during startup ({proc.returncode})")
            try:
                if httpx.get(f"{url}/health", verify=_SSL).json()["strategy"] == strategy:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"the {strategy} shop did not start in {timeout:g} s")
            time.sleep(0.2)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=20)


@dataclass
class ShopRace:
    result: racekit.RunResult
    capacity: int
    #: Reservations after each round (the source of truth for "sold").
    sold: list[int] = field(default_factory=list)

    @property
    def rounds_sold_out(self) -> int:
        return sum(s == self.capacity for s in self.sold)


def reserve_race(
    url: str,
    dsn: str,
    strategy: str,
    *,
    clients: int = 50,
    seats: int = 10,
    rounds: int = 20,
    seed: int | None = None,
) -> ShopRace:
    db = psycopg.connect(dsn, autocommit=True)
    opened: list[httpx.Client] = []
    race = ShopRace(result=racekit.RunResult(seed=0, clients=clients), capacity=seats)

    def prepare(i: int) -> httpx.Client:
        client = httpx.Client(base_url=url, verify=_SSL, timeout=30)
        client.get("/health")  # open the connection before the race
        opened.append(client)
        return client

    def reserve(i: int, client: httpx.Client) -> httpx.Response:
        return client.post(f"/events/{EVENT}/reserve", json={"student": i})

    def check() -> None:
        now = shopdb.state(db, EVENT)
        assert now is not None
        race.sold.append(now.sold)
        assert now.sold <= now.capacity, f"oversold: {now.sold} reservations, {seats} seats"
        if strategy == "atomic_update":
            assert now.claimed == now.sold, f"claimed {now.claimed} != sold {now.sold}"
        if strategy == "skip_locked":
            assert now.seats_taken == now.sold, f"seats {now.seats_taken} != sold {now.sold}"

    try:
        race.result = racekit.run(
            reserve,
            clients=clients,
            rounds=rounds,
            prepare=prepare,
            reset=lambda: shopdb.reset_event(db, EVENT, seats),
            check=check,
            seed=seed,
        )
    finally:
        for client in opened:
            client.close()
        db.close()
    return race
