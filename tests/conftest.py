from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """DSN of the real PostgreSQL the tests run against. Missing DSN fails, never skips."""
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        pytest.fail("TEST_PG_DSN is not set; start a database with `docker compose up -d --wait`")
    return dsn


@pytest.fixture
def conn(pg_dsn: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(pg_dsn) as connection:
        yield connection
