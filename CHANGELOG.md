# Changelog

## Unreleased

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
