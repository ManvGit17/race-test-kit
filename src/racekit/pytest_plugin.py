"""The pytest plugin, loaded through the ``pytest11`` entry point when the package is installed.

- ``race`` fixture: a ``racekit.Race`` for the test.
- ``--race-rounds N`` / ``--race-seed S``: defaults for every ``race`` in the session, so CI
  can run more rounds than a quick local run without touching the tests.
- ``@pytest.mark.race(rounds=..., seed=...)``: defaults for one test; beats the options.
- When a test that used ``race`` fails, its output gets a "racekit" section with every run's
  report, including the seed to rerun with.

Kept cheap to import: pytest imports it in every session once the package is installed.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from racekit.race import Race

_RACE = pytest.StashKey[Race]()
_MARKER_ARGS = {"rounds", "seed"}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("racekit", "race testing (pytest-racekit)")
    group.addoption(
        "--race-rounds",
        type=int,
        default=None,
        help="rounds for every race that does not set its own (marker or argument)",
    )
    group.addoption(
        "--race-seed",
        type=int,
        default=None,
        help="seed for every race that does not set its own, to repeat a run's inputs",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "race(rounds=None, seed=None): defaults for the race fixture in this test"
    )


@pytest.fixture
def race(request: pytest.FixtureRequest) -> Race:
    """A ``racekit.Race``: ``race.run``, ``race.duplicate``, ``race.lost_update``,
    ``race.interleave`` and ``race.arun``, with the marker's and options' defaults."""
    marker = request.node.get_closest_marker("race")
    settings: dict[str, int | None] = {
        "rounds": request.config.getoption("race_rounds"),
        "seed": request.config.getoption("race_seed"),
    }
    if marker is not None:
        unknown = set(marker.kwargs) - _MARKER_ARGS
        if marker.args or unknown:
            pytest.fail(
                f"@pytest.mark.race takes only rounds= and seed=; got {marker.args or ''}"
                f" {sorted(unknown) or ''}".strip(),
                pytrace=False,
            )
        settings.update(marker.kwargs)
    found = Race(rounds=settings["rounds"], seed=settings["seed"])
    request.node.stash[_RACE] = found
    return found


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if report.when == "call" and report.failed:
        found = item.stash.get(_RACE, None)
        if found is not None and found.results:
            report.sections.append(("racekit", found.report()))
    return report
