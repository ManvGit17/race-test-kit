"""The runner on its own, with plain Python calls: no HTTP, no database."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

import racekit


def _no_racekit_threads_left(timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not [t for t in threading.enumerate() if t.name.startswith("racekit-")]:
            return True
        time.sleep(0.01)
    return False


def test_every_client_is_called_once_per_round() -> None:
    seen: list[tuple[int, int]] = []
    lock = threading.Lock()
    rounds = {"n": 0}

    def reset() -> None:
        rounds["n"] += 1

    def call(i: int) -> int:
        with lock:
            seen.append((rounds["n"], i))
        return i * 10

    result = racekit.run(call, clients=5, rounds=3, reset=reset)

    assert result.rounds_run == 3
    assert sorted(seen) == [(r, i) for r in (1, 2, 3) for i in range(5)]
    assert [c.value for c in result.rounds[0].calls] == [0, 10, 20, 30, 40]
    assert _no_racekit_threads_left()


def test_calls_in_a_round_overlap() -> None:
    active = 0
    most = 0
    lock = threading.Lock()

    def call(i: int) -> None:
        nonlocal active, most
        with lock:
            active += 1
            most = max(most, active)
        time.sleep(0.05)
        with lock:
            active -= 1

    racekit.run(call, clients=8, rounds=2)
    assert most == 8


def test_reset_runs_before_and_check_after_each_round() -> None:
    log: list[str] = []
    lock = threading.Lock()

    def call(i: int) -> None:
        with lock:
            log.append("call")

    racekit.run(
        call,
        clients=2,
        rounds=2,
        reset=lambda: log.append("reset"),
        check=lambda: log.append("check"),
    )
    assert log == ["reset", "call", "call", "check"] * 2


@pytest.mark.parametrize(
    ("check", "violated", "message"),
    [
        (lambda: True, False, None),
        (lambda: None, False, None),
        (lambda: False, True, "check returned False"),
    ],
)
def test_check_outcomes(check: object, violated: bool, message: str | None) -> None:
    result = racekit.run(lambda i: None, clients=2, rounds=1, check=check)  # type: ignore[arg-type]
    assert result.rounds[0].violated is violated
    assert result.rounds[0].check_message == message


def test_assertion_in_check_is_a_violation_with_its_message() -> None:
    def check() -> None:
        assert 3 <= 2, "sold 3 of 2 seats"

    result = racekit.run(lambda i: None, clients=2, rounds=2, check=check)
    assert result.violations == 2
    assert result.rounds[0].check_message is not None
    assert "sold 3 of 2 seats" in result.rounds[0].check_message


def test_other_exception_in_check_stops_the_run() -> None:
    def check() -> None:
        raise KeyError("broken check")

    with pytest.raises(KeyError):
        racekit.run(lambda i: None, clients=2, rounds=3, check=check)
    assert _no_racekit_threads_left()


def test_a_raising_call_is_recorded_and_the_others_finish() -> None:
    def call(i: int) -> int:
        if i == 1:
            raise ValueError("boom")
        return i

    result = racekit.run(call, clients=4, rounds=2)
    first = result.rounds[0]
    assert [c.ok for c in first.calls] == [True, False, True, True]
    assert isinstance(first.calls[1].error, ValueError)
    assert first.errors == {"ValueError": 1}


def test_a_hung_call_times_out_the_round() -> None:
    release = threading.Event()

    def call(i: int) -> None:
        if i == 2:
            release.wait()

    try:
        with pytest.raises(racekit.RoundTimeout, match=r"clients \[2\]"):
            racekit.run(call, clients=3, rounds=1, round_timeout=0.3)
    finally:
        release.set()
    assert _no_racekit_threads_left()


def test_prepare_state_is_passed_to_each_call() -> None:
    result = racekit.run(
        lambda i, state: (i, state), clients=3, rounds=2, prepare=lambda i: f"client-{i}"
    )
    assert [c.value for c in result.rounds[1].calls] == [
        (0, "client-0"),
        (1, "client-1"),
        (2, "client-2"),
    ]


def test_prepare_runs_once_per_client_in_its_own_thread() -> None:
    threads: dict[int, str] = {}

    def prepare(i: int) -> None:
        threads[i] = threading.current_thread().name

    racekit.run(lambda i, state: None, clients=3, rounds=3, prepare=prepare)
    assert threads == {0: "racekit-0", 1: "racekit-1", 2: "racekit-2"}


def test_failing_prepare_raises_before_any_round() -> None:
    called = []

    def prepare(i: int) -> None:
        if i == 1:
            raise ConnectionError("no server")

    with pytest.raises(racekit.PrepareError, match="client 1"):
        racekit.run(lambda i, s: called.append(i), clients=3, rounds=1, prepare=prepare)
    assert called == []
    assert _no_racekit_threads_left()


def test_rng_is_fixed_by_seed_round_and_client() -> None:
    def call(i: int) -> float:
        return racekit.rng().random()

    a = racekit.run(call, clients=3, rounds=2, seed=42)
    b = racekit.run(call, clients=3, rounds=2, seed=42)
    c = racekit.run(call, clients=3, rounds=2, seed=43)

    def values(r: racekit.RunResult) -> list[list[float]]:
        return [[c.value for c in rnd.calls] for rnd in r.rounds]

    assert values(a) == values(b)
    assert values(a) != values(c)
    flat = [v for rnd in values(a) for v in rnd]
    assert len(set(flat)) == len(flat)  # every (round, client) gets its own stream


def test_rng_outside_a_call_raises() -> None:
    with pytest.raises(RuntimeError, match="only available inside a call"):
        racekit.rng()


def test_a_seed_is_chosen_and_recorded_when_not_given() -> None:
    result = racekit.run(lambda i: None, clients=2)
    assert isinstance(result.seed, int)
    assert f"seed {result.seed}" in result.summary()


def test_status_is_read_from_status_code() -> None:
    responses = [SimpleNamespace(status_code=201), SimpleNamespace(status_code=409)]
    result = racekit.run(lambda i: responses[i], clients=2)
    assert [c.status for c in result.rounds[0].calls] == [201, 409]
    assert result.rounds[0].statuses == {201: 1, 409: 1}


def test_spread_and_latency_are_recorded() -> None:
    result = racekit.run(lambda i: time.sleep(0.01), clients=4, rounds=2)
    for rnd in result.rounds:
        assert rnd.spread_ms >= 0.0
        assert all(c.latency_ms >= 9.0 for c in rnd.calls)


def test_summary_names_the_first_violating_round() -> None:
    def check() -> bool:
        return counter["round"] != 2

    counter = {"round": 0}

    def reset() -> None:
        counter["round"] += 1

    result = racekit.run(
        lambda i: SimpleNamespace(status_code=200),
        clients=2,
        rounds=3,
        reset=reset,
        check=check,
        seed=7,
    )
    text = result.summary()
    assert "1 of 3 rounds violated the invariant (33%), 2 clients, seed 7" in text
    assert "first violating round (2): statuses 200 x2; errors none" in text


@pytest.mark.parametrize(("clients", "rounds"), [(1, 1), (0, 1), (2, 0)])
def test_bad_arguments_are_refused(clients: int, rounds: int) -> None:
    with pytest.raises(ValueError):
        racekit.run(lambda i: None, clients=clients, rounds=rounds)
