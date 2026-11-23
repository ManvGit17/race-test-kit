# Learning log

## Phase 0: prior art and scaffold (2026-11-22)

**What was built**

- `research/prior-art-lab/`: a FastAPI endpoint with a real oversell bug (count the seats
  taken, compare, insert) on PostgreSQL 18 in Docker, one probe per existing tool, and
  `run_all.py`, which runs each probe for many rounds (reset, run, count rows) and writes
  `results/`. Two configurations: 50 clients for 10 seats, and 2 clients for 1 seat. A
  `row_lock` version of the endpoint is the control.
- `docs/prior-art.md`: the scorecard and the go verdict. `docs/adr/0001-name-and-positioning.md`:
  the name `pytest-racekit` (import `racekit`) and what to lead with.
- The skeleton: `uv` project with a `src/` layout (`uv init --vcs none`), ruff, `mypy --strict`,
  pytest, a smoke test against a real database, `compose.yaml` (PostgreSQL 18 by default, 16
  and 17 on a profile), and a CI matrix of 5 Pythons × 3 PostgreSQL versions.

**Why**

- Reading summaries was not enough. A new tool, pytest-together, appeared after the plan was
  written and does half the original pitch (barrier start plus an overlap check). The lab then
  found things no README says: its 5 ms check refused every round of the 50-client run even
  though the database showed the race happened every time; pytest-race's start is loose
  enough to miss half the races in the 2-client run; two plugins make requests overlap but
  have nowhere to check the result; Schemathesis's workers never overlap requests to one
  endpoint.
- The database, not the tool, is the ground truth. Counting rows after each round separates
  "the race happened" from "the test noticed", which is the whole point of this project.
- The control (`row_lock`) proves the check raises no false alarms: an invariant check that
  goes red on correct code would be worse than none.
- The naive bug turned out easy to hit: even a plain thread pool caught it almost every time.
  So the lab cannot yet show what a tighter start buys; Phase 1 needs a narrower bug for that.
- `httpx.Client()` builds an SSL context each time (about 140 ms on Windows). Sharing one
  context made rounds 5 times faster. The same cost would distort a real race test if paid
  after the barrier.
- The smoke test fails, rather than skips, without a database, and checks the server's major
  version against `EXPECT_PG_MAJOR`, so each CI job proves it ran against the version it claims.

**Quiz**

1. Why does the lab count rows in the database after each round instead of trusting the
   probe's own pass or fail?
2. pytest-together measured a 16 to 33 ms spread in the 50-client run and refused the test,
   yet every round oversold. Give two reasons a client-side start spread can differ from what
   the server sees.
3. pytest-run-parallel made the requests overlap in every round but never went red. Why can't
   a test written for it check "at most 10 seats sold"?
4. Why did Schemathesis with `--workers 8` send only one request at a time to this API?
5. What does the `row_lock` control run prove, and what would it mean if it had gone red?

## Phase 1: runner core (2026-11-22)

**What was built**

- `racekit.run(call, clients=N, rounds=R, prepare=..., reset=..., check=..., seed=...)`.
  It starts one worker thread per client once, runs `prepare(i)` in each, then for every
  round: `reset()`, release all N calls from a barrier, wait for them, `check()`.
- `runner/gate.py` (the barrier and the spread), `runner/threads.py` (the worker pool),
  `runner/capture.py` (one `CallRecord` per call: value, status, latency, exception),
  `runner/rng.py` (`racekit.rng()`), `runner/rounds.py` (the loop), `invariants/result.py`
  (`RoundResult`, `RunResult`, `summary()`).
- `tests/apps/counter.py`: a standard-library HTTP server on PostgreSQL. `naive` mode reads
  the counter then writes back the value plus one (a lost update); `atomic` mode runs
  `value = value + 1`.
- `bench/phase1_detection.py` runs the naive test and the atomic control 100 times each in
  fresh pytest processes; `bench/spread.py` measures the gate on its own. ADRs 0002 and 0003.

**Why**

- Workers live across rounds and slow setup goes in `prepare`, so neither thread start nor
  connection setup falls inside the race window.
- The barrier has one party more than there are workers: the coordinator. Workers park first,
  so the coordinator's arrival releases them all at once.
- Spread is reported, not used to refuse. With do-nothing calls the gate released 50 threads
  within about 1 ms; the 16 to 33 ms seen in the lab came from the calls fighting for the GIL.
- A raising call is recorded, never re-raised inside the worker: an exception there would
  leave the other workers stuck at the next barrier. A hung call times out the round because
  Python threads cannot be killed.
- `check` returning `False` or raising `AssertionError` is a violation; any other exception
  stops the run, because a broken check must not look like a finding.
- The seed fixes inputs (`racekit.rng()` per seed, round and client), not timing.
- Results: the naive counter was caught in 100 of 100 test runs and in 1000 of 1000 rounds;
  the atomic control had 0 violations in 1000 rounds. A mutation that ignores the check's
  result makes the naive test fail, so the test really depends on the check. The bug is easy
  to hit, so these numbers do not yet show what a tight start buys.

**Quiz**

1. Why does the start barrier have `clients + 1` parties, and what would go wrong with a
   `threading.Event` instead?
2. A worker's call raises. Walk through why the other workers still finish the round, and
   what would happen if the worker re-raised the exception.
3. Why does a `check` that raises `KeyError` stop the run, while one that raises
   `AssertionError` only marks the round as violated?
4. Two runs use the same seed. Which parts of a failing round repeat, and which do not?
5. The gate releases 50 do-nothing threads within about 1 ms, yet the lab measured 16 to
   33 ms with HTTP calls. Where does the difference come from?
