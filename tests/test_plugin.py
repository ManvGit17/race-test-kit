"""The pytest plugin, tested by running pytest inside pytest (``pytester``).

Every inner test file is written without a conftest: the plugin must arrive through the
``pytest11`` entry point alone.
"""

from __future__ import annotations

import pytest


def test_the_race_fixture_needs_no_conftest(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import racekit

        def test_uses_race(race):
            assert isinstance(race, racekit.Race)
            result = race.run(lambda i: i, clients=3)
            assert result.rounds_run == 1
        """
    )
    pytester.runpytest("-p", "no:cacheprovider").assert_outcomes(passed=1)


def test_options_apply_to_every_race(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_one(race):
            result = race.run(lambda i: None, clients=2)
            assert (result.rounds_run, result.seed) == (4, 42)

        def test_two(race):
            assert race.duplicate(lambda: None, copies=2).rounds_run == 4
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider", "--race-rounds", "4", "--race-seed", "42")
    result.assert_outcomes(passed=2)


def test_precedence_argument_then_marker_then_option(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.race(rounds=3)
        def test_marker_beats_option(race):
            assert race.run(lambda i: None, clients=2).rounds_run == 3

        @pytest.mark.race(rounds=3)
        def test_argument_beats_marker(race):
            assert race.run(lambda i: None, clients=2, rounds=2).rounds_run == 2

        def test_option_when_nothing_else(race):
            assert race.run(lambda i: None, clients=2).rounds_run == 5
        """
    )
    pytester.runpytest("-p", "no:cacheprovider", "--race-rounds", "5").assert_outcomes(passed=3)


def test_marker_is_registered_for_strict_markers(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.race(seed=9)
        def test_seeded(race):
            assert race.run(lambda i: None, clients=2).seed == 9
        """
    )
    pytester.runpytest("-p", "no:cacheprovider", "--strict-markers").assert_outcomes(passed=1)


def test_unknown_marker_argument_is_an_error(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.race(rouns=3)
        def test_typo(race):
            pass
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*@pytest.mark.race takes only rounds= and seed=*rouns*"])


def test_a_failing_test_shows_the_racekit_report(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.race(rounds=2, seed=5)
        def test_broken(race):
            result = race.run(lambda i: None, clients=2, check=lambda: False)
            assert result.violations == 0
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*- racekit -*",
            "[[]1[]] run",
            "racekit: 2 of 2 rounds violated the invariant (100%), 2 clients, seed 5",
            "*rerun with seed=5 to repeat the same inputs*",
        ]
    )


def test_a_passing_test_shows_no_report(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_fine(race):
            race.run(lambda i: None, clients=2)
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider", "-rA")
    result.assert_outcomes(passed=1)
    assert "- racekit -" not in result.stdout.str()


def test_race_arun_in_a_plain_test(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import asyncio

        async def call(i):
            return i

        def test_async(race):
            result = asyncio.run(race.arun(call, clients=3))
            assert [c.value for c in result.rounds[0].calls] == [0, 1, 2]
        """
    )
    pytester.runpytest("-p", "no:cacheprovider", "--race-rounds", "2").assert_outcomes(passed=1)
