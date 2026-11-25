# ADR 0007: The asyncio backend, and when each backend fits

Date: 2026-11-23. Windows 11, CPython 3.13 (GIL enabled), 22 logical CPUs.

## Context

The thread backend (ADR 0002) uses one OS thread per client. PLAN.md asks for an asyncio
backend too, "for more clients", and for documentation of when each fits.

## Decision

`await racekit.arun(call, clients=N, ...)` takes an `async def` call and the same arguments as
`racekit.run`; `prepare`, `reset` and `check` may be plain or `async`. Each round creates one
task per client. Every task counts itself as parked and waits on one `asyncio.Event`; when the
last has parked the coordinator sets it, and the loop resumes the tasks one after another, each
noting its release time before starting its call. The coordinator waits with `asyncio.wait`
and a timeout; tasks still running are **cancelled**, which threads cannot be, and the round
raises `RoundTimeout`. Call errors are caught as `Exception`, not `BaseException`, so
cancellation is never swallowed.

`racekit.rng()` moved from thread-local storage to a `ContextVar`: each thread has its own
context and each task gets its own copy, so both backends give the same numbers for the same
seed, round and client (tested).

## Measured

`bench/spread.py` (`bench/results/spread.json`), calls that do nothing, median of 30 rounds:

| clients | threads | asyncio |
|---|---|---|
| 2 | 0.02 ms | 0.01 ms |
| 50 | 0.76 ms | 0.43 ms |
| 300 | 4.78 ms | 2.84 ms |

`bench/phase4_backends.py --runs 5` (`bench/results/phase4-backends.json`): 50 students, 10
seats, the `naive` shop, 100 rounds per backend, alternating runs:

| | threads (`httpx.Client`) | asyncio (`httpx.AsyncClient`) |
|---|---|---|
| rounds oversold | 96 of 100 | 99 of 100 |
| start spread, median | 15.6 ms | 27.2 ms |
| latency p50 | 53.5 ms | 71.6 ms |

**With real HTTP calls the asyncio start was looser, not tighter.** The loop resumes tasks one
at a time, and each runs its call synchronously up to its first `await` (building the request,
`httpx` bookkeeping) before the next task gets the loop. Threads also contend for the GIL, but
the operating system interleaves them. Both caught the naive oversell in almost every round.

## When each fits

- **Threads** (`racekit.run`): the default. Works with any client library, sync or not; tighter
  start with `httpx` at 50 clients on this machine; a hung call cannot be stopped.
- **asyncio** (`racekit.arun`): when the code under test or its client is async already, when
  clients number in the hundreds or more (a task costs far less than a thread), or when a hung
  call must be cancelled. Its spread grows with the work each call does before its first await.

## Consequences

- `duplicate`, `lost_update` and `interleave` are thread-only for now; an async version of each
  is a thin wrapper over `arun`, as the sync ones are over `run`.
- These spreads are measured on the client. Neither backend can see when requests reach the
  server; the prior-art lab's server-side spreads showed the two can differ.
