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
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg
import shopdb

import racekit
from racekit import pg

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
def serve(
    dsn: str,
    strategy: str = "naive",
    modes: Mapping[str, str] | None = None,
    *,
    timeout: float = 60.0,
    pause_points: bool = False,
) -> Iterator[str]:
    """Run the shop and yield its base URL.

    ``strategy`` is ``SHOP_STRATEGY``; ``modes`` set the other features by their lower-case
    name, for example ``serve(dsn, modes={"payments": "unique_key", "wallet": "atomic"})``.
    ``pause_points=True`` sets ``RACEKIT_PAUSE_POINTS=1`` for the shop.
    """
    want = {"strategy": strategy, **(modes or {})}
    env = {f"SHOP_{name.upper()}": value for name, value in want.items()}
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
        env={
            **os.environ,
            "SHOP_DSN": dsn,
            "RACEKIT_PAUSE_POINTS": "1" if pause_points else "0",
            **env,
        },
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + timeout
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"the shop {want} exited during startup ({proc.returncode})")
            try:
                running = httpx.get(f"{url}/health", verify=_SSL).json()
                if all(running[name] == value for name, value in want.items()):
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"the shop {want} did not start in {timeout:g} s")
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


# -- the Phase 3 scenarios ------------------------------------------------------------------


def _warm_clients(url: str) -> tuple[Callable[[int], httpx.Client], list[httpx.Client]]:
    opened: list[httpx.Client] = []

    def prepare(i: int) -> httpx.Client:
        client = httpx.Client(base_url=url, verify=_SSL, timeout=30)
        client.get("/health")  # open the connection before the race
        opened.append(client)
        return client

    return prepare, opened


def duplicate_payment_race(
    url: str, dsn: str, *, copies: int = 5, rounds: int = 20, seed: int | None = None
) -> racekit.RunResult:
    """The same payment, one Idempotency-Key, sent ``copies`` times at once."""
    key = "order-7-attempt-1"
    db = psycopg.connect(dsn, autocommit=True)
    prepare, opened = _warm_clients(url)
    same_charge = racekit.same_response(lambda r: r.json()["charge"])

    def check(this: racekit.RoundResult) -> None:
        charges = shopdb.charges_for_key(db, key)
        assert charges == 1, f"{charges} charges for one Idempotency-Key"
        same_charge(this)

    try:
        return racekit.duplicate(
            lambda client: client.post(
                "/payments", json={"order": 7, "amount": 100}, headers={"Idempotency-Key": key}
            ),
            copies=copies,
            rounds=rounds,
            prepare=prepare,
            reset=lambda: shopdb.reset_payments(db),
            check=check,
            seed=seed,
        )
    finally:
        for client in opened:
            client.close()
        db.close()


def topup_race(
    url: str, dsn: str, *, clients: int = 20, rounds: int = 20, seed: int | None = None
) -> racekit.RunResult:
    """``clients`` top-ups of 10 at once; the balance must grow by 10 per acknowledged one."""
    wallet_id = 1
    db = psycopg.connect(dsn, autocommit=True)
    prepare, opened = _warm_clients(url)
    try:
        return racekit.lost_update(
            lambda i, client: client.post(f"/wallets/{wallet_id}/topup", json={"amount": 10}),
            read=lambda: shopdb.balance(db, wallet_id),
            clients=clients,
            delta=10,
            rounds=rounds,
            prepare=prepare,
            reset=lambda: shopdb.reset_wallet(db, wallet_id, 0),
            seed=seed,
        )
    finally:
        for client in opened:
            client.close()
        db.close()


def pay_cancel_race(
    url: str, dsn: str, *, orders: int = 5, rounds: int = 20, seed: int | None = None
) -> racekit.RunResult:
    """For each of ``orders`` pending orders, a pay and a cancel at once.

    Exactly one of the two may succeed, and the order must end consistent: paid with one
    charge, or cancelled with none.
    """
    db = psycopg.connect(dsn, autocommit=True)
    prepare, opened = _warm_clients(url)

    def check(this: racekit.RoundResult) -> None:
        problems = []
        for state in shopdb.order_states(db):
            if (state.status, state.charges) not in (("paid", 1), ("cancelled", 0)):
                problems.append(f"order {state.id} {state.status} with {state.charges} charges")
        # interleave runs pay 0, cancel 0, pay 1, cancel 1, ...: client i works on order i//2+1
        yes = [0] * orders
        for call in this.calls:
            if call.status == 200:
                yes[call.index // 2] += 1
        both = [k + 1 for k, n in enumerate(yes) if n > 1]
        problems += [f"order {order}: pay and cancel both succeeded" for order in both]
        assert not problems, "; ".join(problems[:3])

    try:
        return racekit.interleave(
            {
                "pay": lambda k, client: client.post(f"/orders/{k + 1}/pay"),
                "cancel": lambda k, client: client.post(f"/orders/{k + 1}/cancel"),
            },
            copies=orders,
            rounds=rounds,
            prepare=prepare,
            reset=lambda: shopdb.reset_orders(db, orders),
            check=check,
            seed=seed,
        )
    finally:
        for client in opened:
            client.close()
        db.close()


async def async_reserve_race(
    url: str, dsn: str, *, clients: int = 50, seats: int = 10, rounds: int = 20
) -> racekit.RunResult:
    """``reserve_race`` on the asyncio backend: one ``httpx.AsyncClient`` per task."""
    db = psycopg.connect(dsn, autocommit=True)
    opened: list[httpx.AsyncClient] = []

    async def prepare(i: int) -> httpx.AsyncClient:
        client = httpx.AsyncClient(base_url=url, verify=_SSL, timeout=30)
        await client.get("/health")  # connect before the race
        opened.append(client)
        return client

    async def reserve(i: int, client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(f"/events/{EVENT}/reserve", json={"student": i})

    def check() -> None:
        state = shopdb.state(db, EVENT)
        assert state is not None
        assert state.sold <= seats, f"oversold: {state.sold} reservations, {seats} seats"

    try:
        return await racekit.arun(
            reserve,
            clients=clients,
            rounds=rounds,
            prepare=prepare,
            reset=lambda: shopdb.reset_event(db, EVENT, seats),
            check=check,
        )
    finally:
        for client in opened:
            await client.aclose()
        db.close()


# -- Phase 5: cashback against a top-up, by load and forced ---------------------------------

WALLET = 1
START_BALANCE = 1000
TOP_UP = 10
PURCHASE = 100  # each purchase in the history; cashback is 1% of the total


def _cashback_check(db: psycopg.Connection[Any], purchases: int) -> Callable[..., None]:
    """Client 0 is the cashback, client 1 the top-up: the balance must include both."""
    cashback = purchases * PURCHASE // 100

    def check(this: racekit.RoundResult) -> None:
        paid, topped = (call.status == 200 for call in this.calls)
        expected = START_BALANCE + (cashback if paid else 0) + (TOP_UP if topped else 0)
        actual = shopdb.balance(db, WALLET)
        if actual != expected:
            lost = "the top-up" if actual == expected - TOP_UP else f"{expected - actual}"
            raise AssertionError(f"balance {actual}, expected {expected}: lost {lost}")

    return check


def cashback_race(
    url: str, dsn: str, *, purchases: int, rounds: int = 1, seed: int | None = None
) -> racekit.RunResult:
    """Load alone: the cashback and a top-up released together, ``rounds`` times."""
    db = psycopg.connect(dsn, autocommit=True)
    shopdb.seed_history(db, WALLET, purchases, PURCHASE)
    prepare, opened = _warm_clients(url)
    try:
        return racekit.interleave(
            {
                "cashback": lambda k, client: client.post(f"/wallets/{WALLET}/cashback"),
                "topup": lambda k, client: client.post(
                    f"/wallets/{WALLET}/topup", json={"amount": TOP_UP}
                ),
            },
            rounds=rounds,
            prepare=prepare,
            reset=lambda: shopdb.reset_wallet(db, WALLET, START_BALANCE),
            check=_cashback_check(db, purchases),
            seed=seed,
        )
    finally:
        for client in opened:
            client.close()
        db.close()


def forced_cashback_race(
    url: str, dsn: str, *, purchases: int, rounds: int = 1
) -> racekit.RunResult:
    """With the pause point: the top-up always lands while the cashback is about to write.

    The shop must run with ``serve(..., pause_points=True)``.
    """
    db = psycopg.connect(dsn, autocommit=True)
    shopdb.seed_history(db, WALLET, purchases, PURCHASE)
    cashback_client = httpx.Client(base_url=url, verify=_SSL, timeout=30)
    topup_client = httpx.Client(base_url=url, verify=_SSL, timeout=30)
    try:
        return pg.force(
            lambda: cashback_client.post(f"/wallets/{WALLET}/cashback"),
            lambda: topup_client.post(f"/wallets/{WALLET}/topup", json={"amount": TOP_UP}),
            at="cashback:before_write",
            dsn=dsn,
            rounds=rounds,
            reset=lambda: shopdb.reset_wallet(db, WALLET, START_BALANCE),
            check=_cashback_check(db, purchases),
            names=("cashback", "topup"),
        )
    finally:
        cashback_client.close()
        topup_client.close()
        db.close()
