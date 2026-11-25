# ADR 0002: Synchronised start and how tight it was

Date: 2026-11-22. Checked on Windows 11, CPython 3.13 (GIL enabled), 22 logical CPUs.

## Context

A race needs calls to overlap inside a window that may be a single database round trip wide.
Starting threads in a loop spreads them over the thread-start cost; the prior-art lab also
showed that anything slow done after the start (opening a connection, building an SSL
context: about 140 ms per `httpx.Client` on Windows) can push calls apart.

How tight the start was matters, but the prior-art lab showed the obvious rule fails:
pytest-together refuses a test whose client-side start spread exceeds 5 ms, and with 50 HTTP
clients it refused all 20 rounds (spread 16 to 33 ms) while the database showed a lost update
in every one of them.

`bench/spread.py` (results in `bench/results/spread.json`, threads rows; re-run on 2026-11-23
when the asyncio backend was added, see ADR 0007) measures the gate's own release cost with
calls that do nothing:

| clients | median spread | worst of 30 rounds |
|---|---|---|
| 2 | 0.02 ms | 0.13 ms |
| 10 | 0.15 ms | 0.29 ms |
| 50 | 0.76 ms | 0.97 ms |
| 100 | 1.59 ms | 2.37 ms |
| 300 | 4.78 ms | 5.93 ms |

So the barrier itself releases 50 threads within about a millisecond. The 16 to 33 ms in the
lab came from the calls: the first threads released start running `httpx` code and hold the
GIL, so the later ones record their start late.

## Decision

- **One long-lived worker thread per client**, reused every round; thread start never falls
  inside the window.
- **A `threading.Barrier` with one party per worker plus the coordinator.** Workers park first;
  the coordinator's arrival releases them.
- **`prepare(i)` runs once per client, in its own worker thread, before round 1.** Slow setup
  goes there, outside the window.
- **Each worker records `perf_counter()` right after leaving the barrier**; the round's spread
  is the gap between the first and the last. It is **reported** (per round, and median and
  worst in the summary), **never used to refuse a round**. A wide spread with violations still
  found a real bug; a wide spread with none is a weak sample, and the summary shows that.

## Alternatives rejected

- **Refuse rounds above a fixed spread (pytest-together's rule).** Fails real findings, as
  measured; the right threshold depends on the machine, the client count and the call.
- **`threading.Event` instead of a barrier.** The coordinator cannot tell when every worker is
  waiting, so early workers start before late ones have even parked.
- **New threads per round.** Puts thread start into every round's window.

## Consequences

- The spread measures when workers *started their call*, on the client. It is not when
  requests reached the server; that would need server-side timing, which a black-box tool
  does not have in general.
- With the GIL, more clients means a wider spread. The asyncio backend (ADR 0007) is the answer
  for many clients; free-threaded CPython may change these numbers, and the bench records
  whether the GIL was on.
