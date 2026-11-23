# Contributing

Bugs and ideas: open an issue. Fixes: open a pull request.

```bash
docker compose up -d --wait
uv sync
TEST_PG_DSN=postgresql://test:test@127.0.0.1:54318/test uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

`docker compose --profile matrix up -d --wait` also starts PostgreSQL 16 and 17 (ports 54316
and 54317), the other versions CI tests.

Tests use a real PostgreSQL, never a mock. The deliberately broken `naive` example strategy
must stay broken: a test proves the plugin still catches it, and that test must not be
weakened to make CI green. Public API changes need an entry in `CHANGELOG.md`.

Numbers in the README come only from committed scripts; commit the script's output with any
change to them.

## The prior-art lab

`research/prior-art-lab/` holds the evidence behind `docs/prior-art.md`. See its README to
re-run it.
