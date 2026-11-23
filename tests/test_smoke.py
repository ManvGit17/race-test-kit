"""Placeholder tests until the runner exists: the package imports, and the database is real."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import psycopg

import racekit


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert racekit.__version__ == version


def test_database_is_the_expected_version(conn: psycopg.Connection[Any]) -> None:
    row = conn.execute("SHOW server_version_num").fetchone()
    assert row is not None
    major = int(row[0]) // 10000
    expected = os.environ.get("EXPECT_PG_MAJOR")
    if expected:  # set by each CI matrix job, so a job cannot pass against the wrong server
        assert major == int(expected)
    assert major >= 16
