"""Scenarios, ready-made checks and the report, with in-memory "services": no HTTP, no database.

Each broken service has its race window held open with a short sleep, so the races are
reliable here; the shop tests (examples/shop) race real PostgreSQL without any sleep.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

import racekit
from racekit import RoundResult

WINDOW = 0.01  # seconds a broken service waits between its read and its write


def response(status: int, **body: Any) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, body=body)


# -- check(round) ---------------------------------------------------------------------------


def test_a_check_with_a_parameter_is_given_the_round() -> None:
    seen: list[RoundResult] = []
    racekit.run(lambda i: response(201), clients=3, rounds=2, check=seen.append)
    assert [r.number for r in seen] == [1, 2]
    assert seen[0].statuses == {201: 3}


def test_a_check_with_only_optional_parameters_is_called_bare() -> None:
    calls: list[str] = []

    def check(note: str = "bare") -> None:
        calls.append(note)

    racekit.run(lambda i: None, clients=2, check=check)
    assert calls == ["bare"]


def test_at_most() -> None:
    result = racekit.run(
        lambda i: response(201 if i < 3 else 409), clients=5, check=racekit.at_most(201, 2)
    )
    assert result.rounds[0].violated
    assert result.rounds[0].check_message == "3 responses with status 201, at most 2 allowed"


def test_same_response_ignores_errors_and_refusals() -> None:
    def call(i: int) -> SimpleNamespace:
        if i == 0:
            raise ConnectionError
        return response(409, id=None) if i == 1 else response(200, id=7)

    result = racekit.run(call, clients=4, check=racekit.same_response(lambda r: r.body["id"]))
    assert result.violations == 0
    different = racekit.run(
        lambda i: response(201, id=i), clients=3, check=racekit.same_response(lambda r: r.body)
    )
    assert different.violations == 1
    assert "3 different answers" in (different.rounds[0].check_message or "")


# -- duplicate ------------------------------------------------------------------------------


class Payments:
    """Check-then-insert idempotency, optionally under a lock (the fix)."""

    def __init__(self, locked: bool) -> None:
        self.charges: dict[str, list[int]] = {}
        self.lock = threading.Lock() if locked else None
        self.next_id = 0

    def pay(self, key: str) -> SimpleNamespace:
        if self.lock is not None:
            with self.lock:
                return self._pay(key)
        return self._pay(key)

    def _pay(self, key: str) -> SimpleNamespace:
        if key in self.charges:
            return response(200, charge=self.charges[key][0])
        time.sleep(WINDOW)
        self.next_id += 1
        self.charges.setdefault(key, []).append(self.next_id)
        return response(201, charge=self.next_id)


@pytest.mark.parametrize(("locked", "violations"), [(False, 5), (True, 0)])
def test_duplicate(locked: bool, violations: int) -> None:
    shop = Payments(locked)

    def check(this: RoundResult) -> None:
        assert len(shop.charges["k1"]) == 1, f"{len(shop.charges['k1'])} charges for one key"
        racekit.same_response(lambda r: r.body["charge"])(this)

    result = racekit.duplicate(
        lambda: shop.pay("k1"), copies=4, rounds=5, reset=shop.charges.clear, check=check
    )
    assert result.clients == 4
    assert result.violations == violations, result.report()


def test_duplicate_passes_prepared_state_to_each_copy() -> None:
    result = racekit.duplicate(lambda state: state, copies=3, prepare=lambda i: f"conn-{i}")
    assert sorted(c.value for c in result.rounds[0].calls) == ["conn-0", "conn-1", "conn-2"]


# -- lost_update ----------------------------------------------------------------------------


class Wallet:
    def __init__(self, locked: bool) -> None:
        self.balance = 0
        self.lock = threading.Lock() if locked else None

    def topup(self) -> SimpleNamespace:
        if self.lock is not None:
            with self.lock:
                return self._topup()
        return self._topup()

    def _topup(self) -> SimpleNamespace:
        seen = self.balance
        time.sleep(WINDOW)
        self.balance = seen + 10
        return response(200)


def test_lost_update_is_caught() -> None:
    wallet = Wallet(locked=False)
    result = racekit.lost_update(
        lambda i: wallet.topup(), read=lambda: wallet.balance, clients=5, delta=10, rounds=3
    )
    assert result.violations == 3
    assert "5 updates acknowledged: expected" in (result.rounds[0].check_message or "")
    assert "updates lost" in (result.rounds[0].check_message or "")


def test_no_lost_update_under_a_lock() -> None:
    wallet = Wallet(locked=True)
    result = racekit.lost_update(
        lambda i: wallet.topup(), read=lambda: wallet.balance, clients=5, delta=10, rounds=3
    )
    assert result.violations == 0, result.report()


def test_lost_update_counts_only_acknowledged_updates() -> None:
    """A service that refuses half the updates (409) and applies the rest is correct."""
    balance = {"value": 100}
    lock = threading.Lock()

    def apply(i: int) -> SimpleNamespace:
        if i % 2:
            return response(409)
        with lock:
            balance["value"] += 1
        return response(201)

    result = racekit.lost_update(
        apply,
        read=lambda: balance["value"],
        clients=6,
        rounds=2,
        reset=lambda: balance.update(value=100),
    )
    assert result.violations == 0, result.report()


# -- interleave -----------------------------------------------------------------------------


class Order:
    """Pay and cancel each check that the order is pending, then act: the classic bug."""

    def __init__(self, guarded: bool) -> None:
        self.status = "pending"
        self.charged = 0
        self.lock = threading.Lock() if guarded else None

    def _act(self, new_status: str) -> SimpleNamespace:
        if self.status != "pending":
            return response(409)
        time.sleep(WINDOW)
        self.status = new_status
        if new_status == "paid":
            self.charged += 1
        return response(200)

    def act(self, new_status: str) -> SimpleNamespace:
        if self.lock is not None:
            with self.lock:
                return self._act(new_status)
        return self._act(new_status)


@pytest.mark.parametrize(("guarded", "violations"), [(False, 4), (True, 0)])
def test_interleave_pay_against_cancel(guarded: bool, violations: int) -> None:
    orders: list[Order] = []

    def reset() -> None:
        orders[:] = [Order(guarded) for _ in range(3)]

    def check(this: RoundResult) -> None:
        both = sum(o.status != "pending" for o in orders)
        yes = this.statuses[200]
        assert yes == both, f"{yes} steps succeeded for {both} orders"

    result = racekit.interleave(
        {"pay": lambda k: orders[k].act("paid"), "cancel": lambda k: orders[k].act("cancelled")},
        copies=3,
        rounds=4,
        reset=reset,
        check=check,
    )
    assert result.clients == 6
    assert result.steps == ["pay", "cancel"] * 3
    assert result.violations == violations, result.report()


def test_interleave_gives_each_copy_its_number() -> None:
    result = racekit.interleave({"a": lambda k: ("a", k), "b": lambda k: ("b", k)}, copies=2)
    assert [c.value for c in result.rounds[0].calls] == [("a", 0), ("b", 0), ("a", 1), ("b", 1)]


def test_interleave_needs_two_steps() -> None:
    with pytest.raises(ValueError, match="at least two steps"):
        racekit.interleave({"only": lambda k: None})


# -- report ---------------------------------------------------------------------------------


def test_report_shows_steps_violating_rounds_and_errors() -> None:
    def pay(k: int) -> SimpleNamespace:
        if k == 1:
            raise TimeoutError("slow provider")
        return response(200)

    result = racekit.interleave(
        {"pay": pay, "cancel": lambda k: response(409)},
        copies=2,
        rounds=2,
        check=lambda: False,
        seed=11,
    )
    text = result.report()
    assert text.startswith("racekit: 2 of 2 rounds violated the invariant (100%), 4 clients")
    assert "statuses, all rounds: 200 x2, 409 x4" in text
    assert "  step pay: 200 x2" in text
    assert "  step cancel: 409 x4" in text
    assert "errors, all rounds: TimeoutError x2" in text
    assert "violating rounds (first 2 of 2):" in text
    assert "  round 1: check returned False; statuses 200 x1, 409 x2;" in text
    # Clients run pay 0, cancel 0, pay 1, cancel 1: copy 1 of pay is client 2.
    assert "    first error, client 2: TimeoutError('slow provider')" in text
    assert "latency: p50" in text
    assert text.endswith("rerun with seed=11 to repeat the same inputs")


def test_report_of_a_clean_run() -> None:
    text = racekit.run(lambda i: response(201), clients=2, rounds=2).report()
    assert "no round violated the invariant" in text
    assert "violating rounds" not in text
