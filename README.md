# pytest-racekit

Race testing for live services. Your tests pass because they send one request at a time.
pytest-racekit releases many requests from one starting gate, repeats that for many rounds,
and reports in how many rounds an invariant broke: a seat sold twice, a payment charged twice,
an update lost.

> **Status: alpha.** The API may still change before 1.0.

## What it is and is not

- It finds races in a running service by black-box load with a synchronised start, and checks
  invariants after every round, usually in the database.
- It is **not** a model checker and does not prove that a race is absent. A clean run is a
  sample, which is why it reports rounds, not a single pass or fail.

## Install

```bash
pip install "pytest-racekit[pg]"
```

The `pg` extra adds psycopg 3 (the binary build, so no PostgreSQL client library is needed)
for the PostgreSQL helpers. Installing is enough for pytest to
load the plugin: no conftest changes.

## Quick start

```python
import httpx


def test_never_oversells(race, db):
    def reserve(i, client):
        return client.post("/events/1/reserve", json={"student": i})

    result = race.run(
        reserve,
        clients=50,  # released together, every round
        rounds=20,
        prepare=lambda i: httpx.Client(base_url=URL),  # connect before the race starts
        reset=lambda: db.reset_event(1, seats=10),  # before every round
        check=lambda: db.count_sold(1) <= 10,  # after every round
    )
    assert result.violations == 0
```

When the test fails, pytest prints a `racekit` section: rounds violated, start spread, latency,
status mix overall and in the violating rounds, the first violating rounds in full, and the seed.

Options: `--race-rounds N` and `--race-seed S` set defaults for every test;
`@pytest.mark.race(rounds=..., seed=...)` sets them for one test. An argument in the call wins
over the marker, which wins over the option.

## Scenarios

| | races | checks |
|---|---|---|
| `race.run(call, clients=N)` | N different callers at once | your `check` |
| `race.duplicate(call, copies=5)` | the same request N times (retries, double clicks) | your `check`, e.g. `racekit.same_response(...)` |
| `race.lost_update(apply, read=..., clients=N, delta=d)` | N read-modify-write updates | built in: every acknowledged update counted |
| `race.interleave({"pay": pay, "cancel": cancel}, copies=k)` | different steps at once | your `check`; statuses shown per step |
| `await race.arun(async_call, clients=N)` | like `run`, on asyncio | your `check` |

A `check()` passes unless it returns `False` or raises `AssertionError`; a `check(round)` also
gets the round's responses.

## Forcing a rare interleaving

Some races need one exact order of events, and load hits it only sometimes. Put a pause point
in the app where the window is, and make the order happen every round:

```python
from racekit import pg

# in the app, a no-op unless RACEKIT_PAUSE_POINTS=1:
pg.pause_point(conn, "cashback:before_write")

# in the test:
result = pg.force(
    pay_cashback,
    top_up,
    at="cashback:before_write",
    dsn=DSN,
    rounds=10,
    reset=reset_wallet,
    check=balance_includes_both,
)
```

`pg.Snapshot(conn, tables)` copies tables once and restores them before each round
(`reset=snapshot.restore`).

## Outside pytest

```bash
racekit run scenarios.py --rounds 50 --seed 7
```

Runs every `race_*(race)` function in the file, the same function a test would be. Exit 0 if
all pass, 1 if any fail, 2 if the file cannot be loaded.

## Measured on the demo shop

`examples/shop` is a FastAPI + PostgreSQL shop where every feature has a version broken on
purpose and a fixed one. Each number below comes from a committed script; the full results,
machine and versions are in `bench/results/`.

| what | broken | fixed | script |
|---|---|---|---|
| 50 students, 10 seats (`naive` vs `row_lock`, `atomic_update`, `skip_locked`) | oversold in 90 of 100 rounds | 0 of 100 each | `bench/shop_strategies.py` |
| one payment sent 5 times | caught in 100 of 100 rounds | 0 of 100 | `bench/shop_scenarios.py` |
| 20 top-ups at once | caught in 100 of 100 rounds | 0 of 100 | `bench/shop_scenarios.py` |
| pay against cancel on 5 orders | caught in 100 of 100 rounds | 0 of 100 | `bench/shop_scenarios.py` |
| cashback against a top-up, load alone | the 2-round test failed in 36 of 100 runs | 0 of 100 | `bench/pause_points.py` |
| the same, with the pause point | failed in 100 of 100 runs | 0 of 100 | `bench/pause_points.py` |

## Choosing clients and rounds

- Races are probabilistic: run enough rounds that a bug caught in a fraction of them is still
  caught at least once. Raise `--race-rounds` on CI rather than editing tests.
- Connect in `prepare`, not in the call: first-call costs spread the start out.
- Watch the start spread in the report. Threads are the default; `arun` suits async clients and
  hundreds of clients, but with `httpx` it started 50 clients less tightly than threads on our
  machine (ADR 0007).
- Each round starts the clients in a different shuffled order (fixed by the seed), so a race
  that depends on who goes first is not hidden by the barrier's own wake-up order.
- Keep one test that the broken version is still caught; it tells you the settings still work on
  your hardware.

## Docs

[Prior art](https://github.com/ManvGit17/race-test-kit/blob/main/docs/prior-art.md) · [ADRs](https://github.com/ManvGit17/race-test-kit/tree/main/docs/adr) ·
[Changelog](https://github.com/ManvGit17/race-test-kit/blob/main/CHANGELOG.md) · [Contributing](https://github.com/ManvGit17/race-test-kit/blob/main/CONTRIBUTING.md)

## Licence

Apache-2.0
