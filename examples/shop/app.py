"""The demo shop: one reserve endpoint, four inventory strategies.

    SHOP_DSN=postgresql://test:test@127.0.0.1:15418/test SHOP_STRATEGY=naive \\
        uv run uvicorn app:app --app-dir examples/shop --port 8000

``SHOP_STRATEGY`` picks how seats are claimed (see ``strategies.py``); ``naive`` oversells on
purpose. The tables are created on startup if they are missing.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import shopdb
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel
from strategies import STRATEGIES, Outcome, reserve

DSN = os.environ.get("SHOP_DSN", "postgresql://test:test@127.0.0.1:15418/test")
STRATEGY = os.environ.get("SHOP_STRATEGY", "naive")
if STRATEGY not in STRATEGIES:
    raise SystemExit(f"SHOP_STRATEGY must be one of {', '.join(STRATEGIES)}, not {STRATEGY!r}")

STATUS = {
    Outcome.HELD: 201,
    Outcome.FULL: 409,
    Outcome.ALREADY: 409,
    Outcome.BUSY: 503,
    Outcome.NO_EVENT: 404,
}

pool: ConnectionPool[Any] = ConnectionPool(DSN, min_size=4, max_size=20, open=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool.open(wait=True)
    with pool.connection() as conn:
        shopdb.apply_schema(conn)
    yield
    pool.close()


app = FastAPI(title="racekit demo shop", lifespan=lifespan)


class ReserveBody(BaseModel):
    student: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"strategy": STRATEGY}


@app.post("/events/{event_id}/reserve")
def reserve_seat(event_id: int, body: ReserveBody) -> JSONResponse:
    with pool.connection() as conn:
        outcome = reserve(conn, STRATEGY, event_id, body.student)
    return JSONResponse({"result": outcome.value}, status_code=STATUS[outcome])


@app.get("/events/{event_id}")
def event(event_id: int) -> JSONResponse:
    with pool.connection() as conn:
        state = shopdb.state(conn, event_id)
    if state is None:
        return JSONResponse({"error": "no such event"}, status_code=404)
    return JSONResponse({"capacity": state.capacity, "taken": state.sold})
