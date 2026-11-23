# Prior-art lab

The evidence behind [`docs/prior-art.md`](../../docs/prior-art.md). Every existing tool is
pointed at the same small service with a real oversell bug, for many rounds, and the database
says in which rounds the race actually happened.

## What is here

- `labapp.py`: a FastAPI app with one endpoint, `POST /events/1/reserve`. With
  `LAB_STRATEGY=naive` (default) it counts the seats taken, compares, then inserts: two
  requests can both see a free seat. With `LAB_STRATEGY=row_lock` it locks the event row
  first and must never oversell.
- `schema.sql`, `compose.yaml`: one PostgreSQL 18 container on port 5433, capped at 256 MB.
- `probes/`: one test per tool, all sending the same request with the same pre-warmed
  `httpx` clients, so they differ only in how they start the requests.
- `run_all.py`: starts the app, runs every probe for N rounds (reset, run, read the
  database) and writes `results/<label>/`.

## Run it

```bash
docker compose up -d --wait
uv run --no-project --python 3.13 python run_all.py --label wide --rounds 20
uv run --no-project --python 3.13 python run_all.py --label pair --clients 2 --seats 1 --rounds 40
docker compose down
```

Each probe runs in its own throwaway environment holding only its tool, because pytest loads
every plugin installed. Timings depend on the machine; `results/<label>/*.json` records the
Python version, platform and package versions of every run.
