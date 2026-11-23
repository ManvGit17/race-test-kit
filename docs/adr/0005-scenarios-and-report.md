# ADR 0005: Scenarios, checks that see responses, and the failure report

Date: 2026-11-23.

## Context

`racekit.run` releases N calls and checks an invariant after each round. Three races come up
again and again, each needing a little glue around `run`:

- **Duplicate requests**: a retried payment, a double click. The same request, several times.
- **Lost updates**: many read-modify-write updates; the result must account for every one.
- **Interleaving steps**: two *different* operations on one thing, such as pay against cancel.

Some invariants live in the responses rather than the database: "every copy of a payment got
the same charge id", "pay and cancel did not both say yes". The Phase 1 `check()` took no
arguments, so it could not see them.

## Decision

**Scenarios are thin wrappers over `run`** (`src/racekit/scenarios/`), so rounds, reset, seed,
spread and the report behave identically everywhere:

- `duplicate(call, copies=5)`: `call()` takes no index, because every copy is the same request
  (`call(state)` with `prepare`).
- `lost_update(apply, read=..., clients=N, delta=d)`: reads the value after `reset`, and after
  the round requires `start + d × acknowledged updates`. Only acknowledged updates count (a
  2xx, or no exception for a non-HTTP call), so a service that correctly refuses some updates
  under contention is not accused of losing them.
- `interleave({"pay": pay, "cancel": cancel}, copies=k)`: client `i` runs step
  `names[i % len(steps)]` on copy `i // len(steps)`, so copy `k` of every step can act on the
  same thing (order `k`). The result records each client's step.

**A check that takes one argument is given the round** (`check(round)`), decided by its
signature. One name, `check`, covers both kinds of invariant, and a database check with no
parameters keeps working. Two ready-made response checks: `at_most(status, n)` and
`same_response(key)`.

**`report()` is the failure message; `summary()` stays short.** The report shows the
violation count and rate, the start spread, p50/p95/max latency, the status mix across all
rounds and across violating rounds, the status mix per step for `interleave`, any exceptions,
up to three violating rounds in full (check message, statuses, spread, first error), and the
seed. The two mixes side by side show what changed in the rounds that broke.

## The shop examples

Each scenario has a broken and a fixed version in `examples/shop`, chosen by one environment
variable per feature (`SHOP_PAYMENTS`, `SHOP_WALLET`, `SHOP_ORDERS`):

| scenario | broken | fixed |
|---|---|---|
| duplicate (`POST /payments`) | look the key up, then insert a charge | claim the key with `INSERT ... ON CONFLICT DO NOTHING` on a primary key; losers wait for the winner's commit and return its charge |
| lost_update (`POST /wallets/{id}/topup`) | read the balance, write `read + amount` | `UPDATE ... SET balance = balance + amount` |
| interleave (`POST /orders/{id}/pay`, `/cancel`) | read the status, act if pending | `UPDATE ... WHERE status = 'pending' RETURNING id`: the change is the check |

The fixes all move the decision into one statement PostgreSQL serialises; at READ COMMITTED,
an `UPDATE` that waited on a row re-checks its `WHERE` against the committed row.

Measured with `bench/phase3_scenarios.py --rounds 100` (`bench/results/phase3-scenarios.json`):
every broken version violated in 100 of 100 rounds; every fixed version in 0 of 100.

## Alternatives rejected

- **A separate `check_round=` argument.** Two names for one idea; easy to pass the wrong one.
- **Scenarios with their own loop.** Would duplicate the gate, timeouts and reporting, and
  drift from `run`.
- **`lost_update` comparing against `clients × delta`.** Accuses correct services that refuse
  some updates (optimistic locking with a 409).
- **Broken and fixed endpoints side by side** (`/v1/pay`, `/v2/pay`). One variable per feature
  matches `SHOP_STRATEGY`, and a test talks to one version only.

## Consequences

- Like the oversell and the counter, these broken versions have no artificial delay and are
  caught in every round: they show the scenarios work, not how rare a race they can find. That
  is Phase 5's job (pause points).
- A `check` with a required positional parameter always gets the round; a check that wants
  something else must take it with a default or a closure.
