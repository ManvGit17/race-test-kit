"""``racekit run`` against the shop: exit 1 when a scenario finds a race, 0 when it does not.

Runs the installed ``racekit`` command in a subprocess on ``examples/shop/race_shop.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from harness import serve

SCENARIOS = Path(__file__).resolve().parents[1] / "race_shop.py"


@pytest.fixture(scope="module")
def shop(request: pytest.FixtureRequest, pg_dsn: str) -> Iterator[str]:
    strategy, wallet = request.param
    with serve(pg_dsn, strategy, modes={"wallet": wallet}) as url:
        yield url


def racekit_run(*args: str, url: str = "", dsn: str = "") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SHOP_URL": url, "TEST_PG_DSN": dsn}
    return subprocess.run(
        [sys.executable, "-m", "racekit.cli", "run", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize("shop", [("naive", "read_modify_write")], indirect=True)
def test_exit_1_when_the_shop_is_broken(shop: str, pg_dsn: str) -> None:
    done = racekit_run(str(SCENARIOS), "--rounds", "10", "--seed", "3", url=shop, dsn=pg_dsn)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "FAIL race_never_oversells: race_shop.py:" in done.stdout
    assert ": assert result.violations == 0" in done.stdout
    assert "oversold:" in done.stdout  # from the report printed after the failure
    assert "FAIL race_top_ups_all_count" in done.stdout
    assert "seed 3" in done.stdout
    assert "racekit: 0 passed, 2 failed" in done.stdout


@pytest.mark.parametrize("shop", [("row_lock", "atomic")], indirect=True)
def test_exit_0_when_the_shop_is_fixed(shop: str, pg_dsn: str) -> None:
    done = racekit_run(str(SCENARIOS), "--rounds", "10", url=shop, dsn=pg_dsn)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "racekit: 2 passed, 0 failed" in done.stdout


@pytest.mark.parametrize("shop", [("row_lock", "atomic")], indirect=True)
def test_k_selects_scenarios(shop: str, pg_dsn: str) -> None:
    done = racekit_run(str(SCENARIOS), "-k", "top_ups", "--rounds", "2", url=shop, dsn=pg_dsn)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "racekit: 1 passed, 0 failed" in done.stdout


def test_exit_2_for_a_missing_file(tmp_path: Path) -> None:
    done = racekit_run(str(tmp_path / "nope.py"))
    assert done.returncode == 2
    assert "could not load" in done.stdout


def test_exit_2_when_a_file_has_no_scenarios(tmp_path: Path) -> None:
    empty = tmp_path / "empty.py"
    empty.write_text("def helper(race):\n    pass\n", encoding="utf-8")
    done = racekit_run(str(empty))
    assert done.returncode == 2
    assert "no race_* functions" in done.stdout
