# pytest-racekit

Race testing for live services. Your tests pass because they send one request at a time.
This plugin releases many requests from one starting gate, repeats that for many rounds, and
reports in how many rounds a database invariant broke: a seat sold twice, a payment charged
twice, an update lost.

> **Status: planning.** Nothing is installable yet. The design is in
> [`docs/prior-art.md`](docs/prior-art.md) and the ADRs in [`docs/adr/`](docs/adr/).

## What it is and is not

- It finds races in a running service by black-box load with a synchronised start.
- It is **not** a model checker and does not prove that a race is absent. A clean run is a
  sample, which is why it reports rounds, not a single pass or fail.

## Prior art

[`pytest-together`](https://github.com/Nappuccino-tlg/pytest-together) already releases
callables from a barrier and fails a test whose workers did not overlap. pytest-racekit builds
on the same idea for a different job: many rounds against a live service with a reset between
them, invariants checked in the database, ready-made scenarios (duplicate requests, lost
updates), and a calibration mode that fails when a known-broken reference is *not* caught. See
[`docs/prior-art.md`](docs/prior-art.md) for the full comparison and the lab behind it.

## Licence

Apache-2.0
