# ADR 0008: Pause points, forced interleavings and table snapshots

Date: 2026-11-24.

## Context

Every broken example so far (oversell, lost counter, duplicate payment, lost top-up, pay and
cancel) is caught in nearly every round: load alone is enough. Real bugs are often narrower,
needing one particular order of events, and a test that catches one in a third of its runs is
flaky: it gets retried until green. PLAN.md's Phase 5 check: a lost-update test that fails
about half the time by load alone must fail every time with pause points.

## The bug: cashback against a top-up

`examples/shop/cashback.py` (`SHOP_CASHBACK`). The cashback checks eligibility, reads the
balance, adds up last month's spending, then writes back *the balance it read* plus 1%. A
top-up (the atomic one from Phase 3) that commits between that read and the write is lost.

Getting a race that load catches only sometimes took three attempts, each measured:

1. Read, sum, write, with no eligibility check: lost in 60 of 60 rounds at every history size.
   Released together, the cashback always read before the top-up committed.
2. A slow eligibility count before the read: the delays before the read and after it grew
   together with the history, so the rate never came near half (0 to 23%).
3. **The barrier's order.** With two clients, the barrier woke them in the same order every
   round, so the cashback, client 0, always started first. A race that depends on who goes
   first is then caught almost always or almost never, whatever its real odds. The runner now
   shuffles, per round and by the seed, which client each worker runs (`rng.start_order`), and
   the asyncio backend creates its tasks in the same shuffled order. With that, and a
   constant-time eligibility check (`EXISTS`), the share of rounds losing the top-up moved
   between about 15% and 75% from batch to batch.

The share also differs by round: the first round after the clients connect loses the top-up
less often than later ones. The test that "fails about half the time" is therefore defined as
the 2-round load race, which failed in about 40% of runs while calibrating.

## Decision

**Pause points** (`racekit.pg.pause_point(conn, name)`), one line in the app where the window
is. A no-op unless `RACEKIT_PAUSE_POINTS=1`, so production sends no SQL. When enabled it takes
and releases `pg_advisory_lock(NAMESPACE, hashtext(name))`, which blocks while a test holds it.
The fixed first key (`0x52414345`, "RACE") keeps these locks apart from the app's own advisory
locks. The test side, `PausePoints(dsn).hold(name)`, takes the lock on its own connection;
`wait_until_paused()` watches `pg_locks` (a two-key advisory lock appears with `classid` = key
1, `objid` = key 2 as an unsigned oid, `objsubid = 2`) until a session is waiting.

**`racekit.pg.force(first, then, at=..., dsn=...)`**: each round, start `first` in a thread
while holding `at`, wait until it is blocked there, run `then` to completion, release, wait for
`first`, check. The result is an ordinary `RunResult`, so the report and the plugin work.
`then` must not pass through the same pause point, or it waits for the lock the test holds.

**`racekit.pg.Snapshot(conn, tables)`** for resets: `take()` copies each table into an unlogged
`racekit_snap_<table>`; `restore()` truncates all of them in one statement (foreign keys between
them are no obstacle) and reinserts in the listed order, parents first, with
`OVERRIDING SYSTEM VALUE` so identity columns get their saved ids back. Sequences are not reset.

psycopg is an optional extra (`pytest-racekit[pg]`), imported only by the helpers that open a
connection.

## Measured

`bench/phase5_forcing.py --runs 100 --load-rounds 2` (`bench/results/phase5-forcing.json`),
broken cashback with a history of 1000 purchases, fresh clients every run:

| | load alone (2 rounds per run) | pause points (1 round per run) |
|---|---|---|
| broken (`read_modify_write`) | failed in 36 of 100 runs | failed in 100 of 100 runs |
| fixed (`atomic`) | 0 of 100 | 0 of 100 |

36% is closer to a third than to a half; per batch of 10 runs it moved between 2 and 6.

## Alternatives rejected

- **A `sleep` in the broken code** to widen the window. It makes the race easy, which is the
  opposite of what this phase demonstrates, and real bugs have no sleep in them.
- **One 64-bit advisory key** (`hashtextextended`). Could collide with the app's own keys; the
  two-key form with a namespace cannot, and its `pg_locks` columns are easier to match.
- **Pause points switched on by an argument** passed through the app. An environment variable
  needs no plumbing, and an app that never sets it pays nothing.
- **Resetting sequences in `Snapshot`.** More code for ids nobody compares; documented instead.

## Consequences

- The seed now also fixes each round's start order, so a rerun with the same seed repeats the
  order the clients were released in (ADR 0003's deferred item, done because a measurement
  showed it matters).
- Numbers in the Phase 1-4 bench files were measured before the shuffle; they stand for the
  code they were measured with.
