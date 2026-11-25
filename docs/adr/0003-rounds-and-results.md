# ADR 0003: Rounds, checks and the seed

Date: 2026-11-22.

## Context

A race is probabilistic: one clean run is one sample. festrush's `bench/run.py` ran one load
test and checked the database once at the end, which says whether *a* run oversold, not how
often. The plan asks for "violated in 7 of 100 rounds" and a seed to reproduce a failure.

## Decision

**Rounds.** `racekit.run(call, clients=N, rounds=R, reset=..., check=...)` runs `reset()`,
releases N calls, waits for all of them, then runs `check()`, R times. The result keeps every
round: per call the index, return value, status (read from `status_code` if present),
release time, latency and exception; per round whether the check failed and why.
`violations`, `rounds_run` and `violation_rate` summarise them, and the caller chooses the
failure rule (`violations > 0` for a bug that must be caught, `== 0` for a fix).

**Check semantics.** Returning `False` or raising `AssertionError` marks the round violated,
with the message kept. Any other return value passes, so a check written with `assert` and no
`return` works. Any other exception stops the run: a broken check is a bug in the test, and
counting it as a violation would make a broken test look like a finding.

**Errors in calls are data, not violations.** A call that raises is recorded and the round
goes on; the summary shows the error mix. Whether a 500 under load is acceptable is the
user's check to make.

**A hung call stops the run** with `RoundTimeout` naming the stuck clients, because a Python
thread cannot be killed and waiting forever hides the problem.

**The seed fixes inputs, not timing.** Every call gets `racekit.rng()`, seeded from
`f"{seed}:{round}:{client}"` (string seeds are hashed with SHA-512, so this is stable across
machines and runs). The same seed gives the same random inputs to the same client in the same
round. The operating system's thread scheduling is not reproducible, so a seed makes a
failing round's inputs repeatable, not its interleaving. The summary says "rerun with seed=N
to repeat the same inputs", not "to reproduce".

## Alternatives rejected

- **Stop at the first violation.** Cheaper, but loses the rate, which is what tells a user
  whether 20 rounds on their CI are enough.
- **The runner shuffles start order by seed.** Adds machinery whose effect on scheduling was
  not measured; deferred until a measurement says it helps. *(Superseded 2026-11-24: Phase 5
  measured that without it client 0 nearly always starts first; see ADR 0008.)*
- **Count call exceptions as violations.** Mixes "the service errored" with "the invariant
  broke"; they need different fixes.

## Consequences

- The PostgreSQL counter in `tests/apps/counter.py` lost an update in all 1000 rounds of 100
  test runs at 10 clients (`bench/results/phase1-detection.json`): like the lab's oversell, a
  read-then-write with no delay is easy to hit. Showing what tighter starts or more rounds buy
  needs a narrower window, which Phase 5's pause points provide.
