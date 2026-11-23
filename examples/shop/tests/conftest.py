from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """DSN of the real PostgreSQL the shop runs on. Missing DSN fails, never skips."""
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        pytest.fail("TEST_PG_DSN is not set; start a database with `docker compose up -d --wait`")
    return dsn
