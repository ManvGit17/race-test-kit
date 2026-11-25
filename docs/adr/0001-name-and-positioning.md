# ADR 0001: Package name and positioning

Date: 2026-11-22.

## Context

**Names.** Checked on PyPI's JSON API on 2026-11-22 (`https://pypi.org/pypi/<name>/json`):
`racekit`, `pytest-racekit`, `pytest-race-kit`, `race-test-kit` and `pytest-stampede` return
404 (no such project); `stampede` exists. A 404 is not a guarantee: PyPI can still refuse a
name too similar to an existing one, which only shows at the first upload.

**The pytest plugin list.** pytest's `scripts/update-plugin-list.py` (read 2026-11-22) lists
PyPI projects whose names start with `pytest-` or `pytest_`, plus a short hand-picked set. The
`Framework :: Pytest` classifier alone does not get a project listed.

**Neighbours.** The desk check and the lab (see `docs/prior-art.md`) found two tools close to
the original pitch:

- `pytest-together` 0.1.0 (2026-09-22): releases callables from a barrier and fails the test
  when their start times spread wider than 5 ms. One shot, no rounds, no reset, no database.
- `ratecheck` (Go, same author): warms connections, releases one burst at a rate-limited HTTP
  endpoint and checks the limit held. Rate limiters only, one burst.

## Decision

- Distribution name **`pytest-racekit`**, import name **`racekit`** (the plan's `src/racekit/`
  and `racekit run`). The `pytest-` prefix puts it on the plugin list without asking.
- Lead with what no neighbour does: **rounds with a reset between them and a violation rate**
  ("violated in 7 of 100 rounds"), **invariants checked in the database**, **ready-made
  scenarios** (duplicate requests, lost update, interleave), **advisory-lock pause points**
  that force an interleaving, and a **calibration mode** that fails when the broken reference
  is not caught.
- Still measure how tight the start was, but credit `pytest-together` for the overlap check and
  do not present it as new.

## Alternatives rejected

- **`racekit` alone.** Shorter, but not picked up by the plugin list, and less clear on PyPI that
  it is a pytest plugin.
- **`pytest-stampede`.** Free, but "stampede" already names an unrelated package and a cache
  problem (cache stampede), which would confuse searches.
- **Contribute rounds to pytest-together instead.** Its design is one shot of in-process
  callables with a strict overlap rule; rounds, database resets and scenarios would change what
  that package is. Worth an issue linking the two once this exists.

## Consequences

- The README and `docs/prior-art.md` name `pytest-together` up front.
- Forced interleaving (pause points) moves from stretch goal to a main point of difference.
- If `pytest-together` adds rounds later, the remaining differences are the database helpers,
  scenarios and pause points.
