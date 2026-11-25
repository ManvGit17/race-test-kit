# Changelog

## Unreleased

- `racekit.pg` (needs `pip install pytest-racekit[pg]`): `pause_point(conn, name)` for the app
  (a no-op unless `RACEKIT_PAUSE_POINTS=1`), `PausePoints(dsn).hold(name)` and
  `wait_until_paused()` for the test, `force(first, then, at=..., dsn=...)` to run two steps in
  one exact order every round, and `Snapshot(conn, tables)` to restore tables between rounds.
- Both backends shuffle the order clients start in, per round and by the seed. Without it the
  barrier released client 0 first nearly every round.
- The demo shop gains a cashback (`SHOP_CASHBACK`) whose lost top-up load catches only some of
  the time, with a pause point that catches it every time.
- pytest plugin, loaded on install through the `pytest11` entry point: the `race` fixture (a
  `racekit.Race`), `--race-rounds` and `--race-seed`, and `@pytest.mark.race(rounds=, seed=)`.
  A failing test that used `race` gets a "racekit" section with every run's report.
- `racekit run FILE [-k NAME] [--rounds N] [--seed S]`: runs a file's `race_*(race)` functions
  outside pytest; exit 0 if all pass, 1 if any fail, 2 if the file cannot be loaded.
- `racekit.arun`: the asyncio backend, for `async def` calls; a hung call is cancelled.
- `racekit.Race`: the object behind the fixture and the CLI, with `run`, `duplicate`,
  `lost_update`, `interleave` and `arun` plus defaults and a combined `report()`.
- Built-in checks raise `AssertionError` explicitly, so pytest's assertion rewriting does not
  change their messages.
- Scenarios: `racekit.duplicate` (the same request several times at once),
  `racekit.lost_update` (read-modify-write updates; checks every acknowledged one counted) and
  `racekit.interleave` (different named steps at once, with per-step statuses).
- A `check` that takes one argument is given the round's `RoundResult`. Ready-made response
  checks: `racekit.at_most(status, n)` and `racekit.same_response(key)`.
- `RunResult.report()`: the full failure report (rates, spread, latency, status mix overall
  and in violating rounds, per step, errors, the first violating rounds, the seed).
- The demo shop gains broken and fixed payments (`SHOP_PAYMENTS`), wallet top-ups
  (`SHOP_WALLET`) and order pay/cancel (`SHOP_ORDERS`).
- `examples/shop`: a FastAPI demo shop with four inventory strategies chosen by
  `SHOP_STRATEGY` (`naive`, broken on purpose; `row_lock`; `atomic_update`; `skip_locked`), and
  tests that race 50 students at 10 seats against each one.
- `racekit.run(call, *, clients, rounds=1, prepare=None, reset=None, check=None, seed=None,
  round_timeout=30.0)`: releases `clients` calls from one barrier per round, on long-lived
  worker threads, and checks the invariant after every round. Returns a `RunResult` with
  every round's calls (value, status, latency, exception, release time), the start spread,
  `violations`, `violation_rate` and `summary()`.
- `racekit.rng()`: a per-call random generator fixed by the seed, round and client.
- `PrepareError` and `RoundTimeout` for a failed setup and a hung call.
- Project skeleton: packaging, CI with a PostgreSQL service container, and the prior-art lab.
