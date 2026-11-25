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

## Phase 2: demo shop and the four strategies (2026-11-23)

**What was built**

- `examples/shop/`: a FastAPI app with one endpoint, `POST /events/{id}/reserve`, and four
  strategies ported from festrush (`strategies.py`), chosen by `SHOP_STRATEGY`. Three tables:
  events (with a `claimed` counter), reservations (one per student per event) and seats.
- `shopdb.py` resets an event and reads its state straight from PostgreSQL; `harness.py` runs
  the app with uvicorn in a subprocess and races 50 students at 10 seats with `racekit.run`.
- Tests: `naive` must oversell; `row_lock`, `atomic_update` and `skip_locked` must not, and must
  not answer 5xx; the first two must sell every seat. Plus one-request-at-a-time behaviour.
- `bench/phase2_strategies.py` and ADR 0004. Local databases moved to ports 15416-15418.

**Why**

- `naive` counts, then inserts: between the two, other requests count the same number. The
  three fixes stop that in different places: `row_lock` makes claims queue on one row lock;
  `atomic_update` lets one `UPDATE ... WHERE claimed < capacity` decide; `skip_locked` gives
  each buyer a different seat row instead of making them wait for the same one.
- The checks read the database, not the app: the thing under test cannot be its own judge.
- `skip_locked` can answer "busy" when free seats are only locked by claims still in flight,
  so it is not required to sell out; it did sell out in all 100 measured rounds here.
- Results (`bench/results/phase2-strategies.json`): `naive` oversold in 90 of 100 rounds, up to
  27 reservations for 10 seats; the three safe strategies oversold in 0 of 100.
- Ports: Windows reserves blocks of ports in its dynamic range (49152 and up) for Hyper-V and
  WSL at boot. 54318 fell inside one after a restart, so the databases moved below that range.

**Quiz**

1. Walk through two `naive` requests that both take the last seat. Which statement does each
   run, and in what order?
2. In `atomic_update`, why is the reservation inserted *before* the counter is updated, and what
   undoes it when the event is full?
3. What does `SKIP LOCKED` change compared with `FOR UPDATE`, and why can it lead to "busy"?
4. Why do the tests reset and check through the database instead of the app's own endpoints?
5. The UNIQUE constraint stops a student holding two seats even under `naive`. What race does
   `naive` still have, and why doesn't the constraint stop it?

## Phase 3: scenarios and the failure report (2026-11-23)

**What was built**

- `racekit.duplicate`, `racekit.lost_update` and `racekit.interleave`, each a thin layer over
  `racekit.run` (`src/racekit/scenarios/`).
- A `check` with one parameter now receives the round, so it can look at responses;
  `racekit.at_most` and `racekit.same_response` are two ready-made ones.
- `RunResult.report()`: the long failure message.
- Three new shop features, each in a broken and a fixed version, with tests for both and a
  bench: payments with an `Idempotency-Key`, wallet top-ups, and paying or cancelling an order.

**Why**

- Building on `run` means the gate, timeouts, seed and report behave the same in every scenario.
- `lost_update` counts only acknowledged updates: a service that says "conflict, try again" and
  applies nothing is correct, and must not be accused.
- `interleave` gives each step a copy number, so pay copy 3 and cancel copy 3 both work on
  order 4, and five orders race in one round.
- Every fix moves the decision into one statement PostgreSQL serialises: claiming a primary key,
  `balance = balance + amount`, `UPDATE ... WHERE status = 'pending'`. At READ COMMITTED, an
  `UPDATE` that had to wait for another transaction re-checks its `WHERE` on the newly committed
  row; a plain `SELECT` before it does not.
- Results (`bench/results/phase3-scenarios.json`): each broken version violated in 100 of 100
  rounds (the duplicate payment made 499 charges for 100 keys); each fixed one in 0 of 100.

**Quiz**

1. In the fixed payment, five copies arrive together. What does each of the four losers'
   `INSERT ... ON CONFLICT DO NOTHING` wait for, and how does it find the charge id to return?
2. Why does `lost_update` count only acknowledged updates instead of expecting
   `clients × delta`?
3. With `interleave({"pay": ..., "cancel": ...}, copies=5)`, which order does client 7 work on,
   and which step does it run?
4. Name two invariants of the pay/cancel race that the database alone cannot show, and how the
   check sees them.
5. Why does `UPDATE ... SET balance = balance + 10` never lose an update at READ COMMITTED,
   while `SELECT balance` followed by `UPDATE ... SET balance = <value read + 10>` does?

## Phase 4: pytest plugin, asyncio backend and CLI (2026-11-23)

**What was built**

- `racekit.Race` (`race.py`): the library's methods plus default rounds and seed, and a memory
  of every result. Both the fixture and the CLI hand one to a scenario.
- The pytest plugin (`pytest_plugin.py`), loaded through the `pytest11` entry point: the `race`
  fixture, `--race-rounds`, `--race-seed`, `@pytest.mark.race`, and a "racekit" section with
  every report when a test fails.
- `racekit.arun` (`runner/aio.py`): the asyncio backend. `racekit.rng()` now lives in a
  `ContextVar`, so threads and tasks each have their own.
- `racekit run FILE`: runs a file's `race_*(race)` functions outside pytest, with
  `examples/shop/race_shop.py` as the example.
- `scripts/plugin_install_check.py`, `bench/phase4_backends.py`, `--backend` in
  `bench/spread.py`, ADRs 0006 and 0007.

**Why**

- An entry point is what "no conftest changes" means: pip writes it into the package metadata,
  and pytest loads every `pytest11` entry point it finds at startup.
- Precedence is argument, marker, option, default: the most specific setting wins, and CI can
  still raise rounds for every test that did not choose its own.
- The install check runs in a brand-new virtual environment, because the project's own `.venv`
  could hide a missing entry point. It even caught a test of its own that passed for the wrong
  reason: `shutil.which("racekit")` found the project's command on PATH.
- Installing the plugin makes pytest rewrite `assert` inside `racekit` too, which changed the
  built-in checks' messages; they now raise `AssertionError` themselves.
- The asyncio backend can cancel a hung call; threads cannot be killed. But with real `httpx`
  calls its start was looser than threads (median 27.2 ms against 15.6 ms at 50 clients),
  because the loop runs each task up to its first `await` before starting the next. Both
  caught the naive oversell in 96 to 99 of 100 rounds.

**Quiz**

1. What does the `pytest11` entry point in `pyproject.toml` do, and why must the plugin module
   be cheap to import?
2. A test has `@pytest.mark.race(rounds=3)`, pytest runs with `--race-rounds 10`, and the test
   calls `race.run(..., rounds=2)`. How many rounds run, and why that order?
3. Why does the plugin install check use a fresh virtual environment instead of the project's?
4. Why did the asyncio backend start 50 HTTP clients less tightly than threads, when it starts
   50 do-nothing tasks more tightly?
5. Why must `arun` catch `Exception` and not `BaseException` around each call?

## Phase 5: PostgreSQL helpers and forced interleaving (2026-11-24)

**What was built**

- `racekit.pg.pause_point`, `PausePoints`, `force` (`src/racekit/pg/pause.py`, `force.py`):
  hold a request at a named line of the app, using a PostgreSQL advisory lock, and run another
  request while it waits.
- `racekit.pg.Snapshot` (`snapshot.py`): copy tables once, restore them before each round.
- A shuffled start order per round in both backends (`rng.start_order`).
- The shop's cashback, broken and fixed, with a pause point before its write; tests for load
  alone and forced; `bench/phase5_forcing.py`; ADR 0008.

**Why**

- An advisory lock is a lock on a number, not a row, so the test and the app can meet at an
  agreed place without touching any data. The app takes and releases it at once; only while
  the test holds it does the app wait. `pg_locks` shows the waiting session, so the test knows
  when to send the other request.
- Making a race that load catches only *sometimes* was the hard part. The first version lost
  the top-up every round; the second almost never. Measuring which client started first
  showed the real problem: the barrier released client 0 first nearly every round. A race that
  depends on order needs the order shuffled, so the runner now does that, by the seed.
- The load-alone rate is not stable: it moved between about 15% and 75% per batch, and first
  rounds differ from later ones. That is exactly why a test that relies on load for such a bug
  is flaky, and why the pause point is worth one line of app code.
- Results (`bench/results/phase5-forcing.json`): the 2-round load test failed in 36 of 100
  runs; with the pause point, 100 of 100; the fixed cashback in 0 of 100 either way.

**Quiz**

1. Walk through one forced round: who holds which lock, when does the cashback stop, and why
   is the top-up always lost?
2. Why must the `then` step not pass through the same pause point as `first`?
3. A barrier releases threads "together". Why did client 0 still start first almost every
   round, and how does the runner fix it without changing which client gets which state?
4. Why does a pause point cost nothing in production, and what does it cost in a test when
   nobody holds the lock?
5. `Snapshot.restore()` truncates every listed table in one statement. What would go wrong
   with one `TRUNCATE` per table when they reference each other?
