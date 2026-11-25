# ADR 0006: The pytest plugin, the CLI, and the `Race` object they share

Date: 2026-11-23.

## Context

The goal: installing the package makes a `race` fixture available
with no conftest changes. The plan also asks for `--race-rounds`, `--race-seed`, a
`@pytest.mark.race` marker, and `racekit run scenario.py` for use outside pytest.

Two questions: where do the rounds and seed come from when a test does not say, and how do
pytest and the CLI avoid being two different ways to write the same scenario.

## Decision

**One `Race` object** (`src/racekit/race.py`) with the library's methods (`run`,
`duplicate`, `lost_update`, `interleave`, `arun`). It fills in `rounds` and `seed` when a call
leaves them out, and keeps every result. The fixture yields one per test; the CLI makes one
per scenario. A scenario is `def race_x(race): ...`, which is also a valid pytest test body.

**Precedence, most specific first:** an argument in the call, then the marker, then the
command-line option, then the library default (1 round, a random seed). A test that needs
exactly 2 rounds keeps them; a test that did not care follows `--race-rounds`, which is how CI
runs more rounds than a laptop without editing tests.

**Plugin** (`src/racekit/pytest_plugin.py`), registered through the `pytest11` entry point:
the `race` fixture, the two options in a "racekit" option group, the marker registered in
`pytest_configure` (so `--strict-markers` accepts it), and a `pytest_runtest_makereport`
wrapper that adds a "racekit" section with every run's report when a test that used `race`
fails. The fixture rejects unknown marker arguments (`rouns=3`) instead of ignoring them.

**CLI** (`racekit run FILE [-k NAME] [--rounds N] [--seed S]`, a `[project.scripts]` entry):
loads the file, runs its `race_*` functions (`async def` ones through `asyncio.run`), prints
`PASS`/`FAIL` with the failing line, then each run's report. Exit 0 if all passed, 1 if any
failed, 2 if the file could not be loaded or has no scenarios.

**No runtime dependency on pytest.** The plugin module is only imported by pytest itself;
`racekit.run` works without it. Same as pgsql-loupe.

## Found while building

- **pytest rewrites `assert` in installed plugins.** Once `racekit` was an entry-point plugin,
  messages from `at_most` and `lost_update` grew pytest's own explanation ("assert 3 <= 2").
  The library's checks now `raise AssertionError(...)` explicitly.
- **Reports printed twice.** With `assert result.violations == 0, result.report()` inside a
  `Race` scenario, both the assertion and the plugin/CLI printed the report. With `race`, a
  bare `assert result.violations == 0` is enough; the CLI shows the file and line that failed.

## Verified

`scripts/plugin_install_check.py` builds the wheel, installs it with pytest into a fresh
virtual environment, and runs a test file there with no conftest and no configuration: the
fixture exists, `--race-rounds 7` and the marker apply, and the `racekit` command is installed
in that environment.

## Alternatives rejected

- **A fixture that wraps `racekit.run`, and a CLI with its own option plumbing.** Two ways to
  write a scenario, and two places to keep the precedence right.
- **The option overriding everything**, so CI can force more rounds even where a test set
  them. A test that sets rounds usually has a reason (a bound on run time); overriding it
  silently would surprise.
- **A global "current defaults" that `racekit.run` reads.** Action at a distance: library calls
  would change behaviour depending on whether pytest happened to be running.
