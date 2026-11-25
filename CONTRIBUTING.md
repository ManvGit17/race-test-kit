# Contributing

Bugs and ideas: open an issue. Fixes: open a pull request.

```bash
docker compose up -d --wait
uv sync
TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

`docker compose --profile matrix up -d --wait` also starts PostgreSQL 16 and 17 (ports 15416
and 15417), the other versions CI tests.

Tests use a real PostgreSQL, never a mock. The deliberately broken `naive` example strategy
must stay broken: a test proves the plugin still catches it, and that test must not be
weakened to make CI green. Public API changes need an entry in `CHANGELOG.md`.

Numbers in the README come only from committed scripts; commit the script's output with any
change to them.

## Releasing (maintainer)

1. Set the version in `pyproject.toml` and `src/racekit/__init__.py` (a test keeps them equal)
   and date the `CHANGELOG.md` section.
2. `uv build`, `uvx twine check dist/*`, `uv run python scripts/plugin_install_check.py`.
3. Once only: on pypi.org add a trusted publisher (this repository, workflow `release.yml`,
   environment `pypi`), and create the `pypi` environment in the repository settings.
4. Push to `main`, wait for CI, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`.
   The `Release` workflow checks the tag against the version, builds and publishes.

## The prior-art lab

`research/prior-art-lab/` holds the evidence behind `docs/prior-art.md`. See its README to
re-run it.
