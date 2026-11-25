# ADR 0004: The demo shop and its four strategies

Date: 2026-11-23. Ported from festrush-ticketing's `src/festrush/inventory.py`.

## Context

The plugin needs a service with a real bug it must keep catching, and correct versions of the
same service it must never accuse. festrush already had four inventory strategies behind one
function, with orders, holds, expiry, payments and a worker around them. A demo needs the
strategies, not the shop.

## Decision

`examples/shop/` is one FastAPI endpoint, `POST /events/{id}/reserve`, on a psycopg pool, with
the strategy chosen by `SHOP_STRATEGY`. Three tables: `shop_events (capacity, claimed)`,
`shop_reservations (UNIQUE (event_id, student))` and `shop_seats (reservation_id)`.

| strategy | what stops two requests taking the last seat | answers |
|---|---|---|
| `naive` | nothing: count, compare, insert. **Broken on purpose.** | 201, 409 |
| `row_lock` | `SELECT ... FOR UPDATE` on the event row; claims for one event queue | 201, 409 |
| `atomic_update` | insert, then `UPDATE ... claimed = claimed + 1 WHERE claimed < capacity`; no row updated means full, and the insert is rolled back | 201, 409 |
| `skip_locked` | insert, then take a free seat row `FOR UPDATE SKIP LOCKED`; if the only free seats are locked by claims in flight, wait 5, 10, 15 ms and look again, then answer 503 "busy" | 201, 409, 503 |

**Reset and checks go to the database, not the app.** The app is what is under test, so it
must not also be the judge. `shopdb.reset_event` empties the event and recreates its seats;
`shopdb.state` counts reservations (the source of truth), `claimed` and taken seat rows. The
check after each round: reservations never exceed capacity; for `atomic_update` the counter
equals the reservations; for `skip_locked` the taken seats equal the reservations.

**The app runs as a real server** (uvicorn in a subprocess, one strategy at a time), so it never
shares the test's GIL and the requests cross a real socket.

**Tests:** 50 students, 10 seats, 20 rounds per strategy. `naive` must oversell in at least one
round: this is the guard that racekit still catches it. The safe three must never oversell or
answer 5xx; `row_lock` and `atomic_update` must also sell every seat. `skip_locked` is not
required to sell out, because "busy" can legitimately leave a seat unsold in a round.

## Measured

`bench/shop_strategies.py --runs 5 --rounds 20` (`bench/results/shop-strategies.json`),
Windows 11, PostgreSQL 18.7: `naive` oversold in 90 of 100 rounds, selling up to 27 of 10
seats. The other three oversold in 0 of 100 and sold out in 100 of 100; `skip_locked` answered
"busy" 0 times.

## Alternatives rejected

- **Port festrush whole.** Orders, payments and expiry are other races (the duplicate and
  lost-update scenarios, ADR 0005); bundling them makes the demo harder to read.
- **Check through the app's own `GET` endpoint.** A bug in the app could hide itself.
- **Run the app in-process with `TestClient`.** No real socket, and it shares the test's GIL,
  which changes the timing the test is about.
- **Require `skip_locked` to sell out.** It held on this machine, but nothing in the strategy
  promises it; a slower CI runner could see "busy". It stays measured, not asserted.

## Consequences

- `naive` counts before it checks for a duplicate, so a repeat request when the event is full
  answers "full", not "already" (`row_lock` too). festrush has the same order.
- The UNIQUE constraint means even `naive` cannot give one student two seats; the race it shows
  is oversell, not double booking.
