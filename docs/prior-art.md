# Prior art

Checked 2026-11-22 against PostgreSQL 18.7 on Windows 11, Python 3.13.5. Every measured
claim below comes from `research/prior-art-lab` (run `run_all.py`; outputs in
`results/wide/` and `results/pair/`). Claims marked *(source)* come from reading the
package source, and *(docs)* from its README or documentation only.

## The lab in one paragraph

A FastAPI endpoint reserves a seat by counting the seats taken, comparing with the capacity,
then inserting: the check-then-insert oversell bug, with no artificial delay. Each tool is
used the way its README suggests to send the reserve request, with the same pre-warmed
`httpx` clients. A round is: reset the table, run the tool's test once, count the rows. The
database says whether the race happened (**oversold**); the tool's own exit code says
whether the test noticed (**red**). Two configurations: **wide**, 50 clients for 10 seats,
20 rounds; **pair**, 2 clients for 1 seat, 40 rounds. The same barrier start against a
`row_lock` version of the endpoint never oversold and never went red, in 20 + 40 rounds, so
the check itself raises no false alarms.

## Scorecard

| | pytest-together 0.1.0 | pytest-race 0.2.0 | pytest-run-parallel 0.10.0 | pytest-asyncio-concurrent 0.5.2 | Hypothesis 6.170.17 (stateful) | Schemathesis 4.33.4 |
|---|---|---|---|---|---|---|
| Last release | 2026-09 (first and only) | 2022-06 | 2026-08 | 2026-04 | 2026-11 | 2026-11 |
| Built for | proving a concurrency test overlapped | one function in N threads | thread-safety of C extensions (free-threading) | faster async test suites | sequential stateful properties | API fuzzing from a schema |
| Requests really overlap (wide: rounds oversold) | yes, 20 of 20 | yes, 17 of 20 | yes, 20 of 20 | yes, 19 of 20 | **no**, 0 of 5 | **no**, 0 of 5 |
| Requests really overlap (pair: rounds oversold) | yes, 40 of 40 | **19 of 40** | yes, 40 of 40 | yes, 40 of 40 | no, 0 of 5 | no, 0 of 5 |
| Test can check "at most N sold" | yes | yes | **no**: each thread runs its own copy of the test | **no**: each request is its own test | yes, after each step | yes, a custom check after each response |
| Test went red when the race happened | **wide: 0 of 20** (refused all 20 as "not concurrent"); pair: 40 of 40 | wide: 17 of 17; pair: 19 of 19 | never (0 of 60) | never (0 of 59) | n/a, no race | n/a, no race |
| Measures how tight the start was | **yes**: client-side start spread, fails above 5 ms | no | no | no | no | no |
| Rounds with a reset between them | no | no | `--iterations`, no reset hook | no | yes (examples), reset in `initialize` | no |
| Reports a violation rate over rounds | no | no | no | no | no | no |
| Database invariants, scenarios, forced interleaving | no | no | no | no | no | no |

Reviewed from docs and source only, not run:

- **ratecheck** (Go, same author as pytest-together) *(docs)*: warms one HTTP/1.1 connection
  per request, releases one burst against a rate-limited endpoint, measures the spread on the
  wire with Go's `httptrace`, and reports whether the limit held, from response codes. It fits
  "live HTTP, synchronised start, invariant", but only for rate limiters, as one burst, with
  no database and no pytest.
- **race-the-web** (Go) *(docs)*: sends simultaneous requests and compares the responses for
  differences, with a REST API for CI. No invariants beyond "the responses differ".
- **Burp Turbo Intruder, race.py, h2spacex** *(docs)*: security tools built on James Kettle's
  single-packet attack (hold back the last frame of every HTTP/2 stream, send them all in one
  TCP packet) and HTTP/1.1 last-byte sync. They make the start far tighter than threads can;
  judging the result is left to the tester.
- **Locust, k6** *(docs)*: load generators. festrush's `bench/run.py` uses Locust with every
  user spawned at once and checks invariants afterwards; it is the starting point for this
  project, not a reusable tool.

## Notes

- **pytest-together is the closest tool, and its overlap check is the right idea.** But in
  the wide configuration it refused every round (`NotConcurrent: workers started 16 to 33 ms
  apart`) while the database showed an oversell in all 20 of them. Its spread is measured on
  the client, right after the barrier: on this machine, waking 50 Python threads takes longer
  than its 5 ms default. With 2 workers the spread was 0.4 ms and it caught all 40 races. So
  the default tolerance is too tight for wide runs on Windows, and a client-side spread is not
  the spread the server saw (server-side spreads in `results/` differ from client-side ones).
- **pytest-race's start is the loosest.** In the pair configuration the two requests reached
  the server a median 15.4 ms apart (others: 0.1 to 0.2 ms), and only 19 of 40 rounds raced.
  *(source)* Its main thread waits for the workers in a loop with no sleep, competing with
  them for the GIL, and workers pass through a barrier and then an event.
- **pytest-run-parallel and pytest-asyncio-concurrent make requests overlap but cannot fail
  on the result.** They run N copies of a test, so no single test sees all N responses. They
  were green in all 119 rounds where the database was oversold.
- **pytest-asyncio-concurrent's natural form is broken on pytest 9.2.0.** With
  `@pytest.mark.parametrize` every test in the group errors at teardown ("The fixture value
  for "i" is not available during teardown") and sends nothing (3 of 3 rounds). Tests
  defined one by one in a loop work.
- **Sequential tools cannot see this bug.** Hypothesis runs rules one after another.
  Schemathesis's `--workers` *(source)* is capped at the number of API operations
  (`workers_num=min(workers, total_entries)`), so 8 workers against one endpoint still send
  one request at a time. Neither oversold in any round.
- **This bug is easy to hit.** With no artificial delay, even a plain `ThreadPoolExecutor`
  oversold in 19 of 20 wide rounds and 40 of 40 pair rounds; a barrier added nothing
  measurable here. A bug with a narrower window will be needed to show what a tighter start
  buys (Phase 1's counter, Phase 5's pause points).
- **Lab trap worth keeping:** creating an `httpx.Client` costs about 140 ms on Windows
  because each one builds its own SSL context, even for plain `http://`. Fifty of them made
  every round take 10 seconds until the probes shared one context.

## Verdict

**Go, with the narrower positioning in ADR 0001.** No tool runs a live service for many
rounds with a reset between them and reports how many rounds broke a database invariant.
The ones whose requests overlap either cannot express the invariant (pytest-run-parallel,
pytest-asyncio-concurrent), or are one shot with no reset (pytest-together, pytest-race),
and the sequential ones never trigger the race at all. pytest-together's overlap check is
prior art for "measure how tight the start was" and is credited as such; this lab also shows
why a fixed 5 ms client-side threshold is not enough on its own.
