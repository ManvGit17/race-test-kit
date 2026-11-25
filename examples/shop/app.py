"""The demo shop: each feature comes in a broken version and a fixed one.

    SHOP_DSN=postgresql://test:test@127.0.0.1:15418/test SHOP_STRATEGY=naive \\
        uv run uvicorn app:app --app-dir examples/shop --port 8000

One environment variable per feature picks the version; the first in each list is broken on
purpose and is the default.

- ``SHOP_STRATEGY``, ``POST /events/{id}/reserve``:
  naive, row_lock, atomic_update, skip_locked
- ``SHOP_PAYMENTS``, ``POST /payments`` with an ``Idempotency-Key`` header:
  check_then_insert, unique_key
- ``SHOP_WALLET``, ``POST /wallets/{id}/topup``: read_modify_write, atomic
- ``SHOP_ORDERS``, ``POST /orders/{id}/pay`` and ``/cancel``: check_then_act, guarded_update
- ``SHOP_CASHBACK``, ``POST /wallets/{id}/cashback``: read_modify_write, atomic

``RACEKIT_PAUSE_POINTS=1`` turns on the pause point in the cashback (see ``cashback.py``).

The tables are created on startup if they are missing.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import cashback
import orders
import payments
import shopdb
import wallet
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel
from strategies import STRATEGIES, Outcome, reserve

DSN = os.environ.get("SHOP_DSN", "postgresql://test:test@127.0.0.1:15418/test")


def _setting(name: str, choices: Sequence[str]) -> str:
    value = os.environ.get(name, choices[0])
    if value not in choices:
        raise SystemExit(f"{name} must be one of {', '.join(choices)}, not {value!r}")
    return value


MODES = {
    "strategy": _setting("SHOP_STRATEGY", STRATEGIES),
    "payments": _setting("SHOP_PAYMENTS", payments.MODES),
    "wallet": _setting("SHOP_WALLET", wallet.MODES),
    "orders": _setting("SHOP_ORDERS", orders.MODES),
    "cashback": _setting("SHOP_CASHBACK", cashback.MODES),
}

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


@app.get("/health")
def health() -> dict[str, str]:
    return MODES


# -- seats ----------------------------------------------------------------------------------


class ReserveBody(BaseModel):
    student: int


@app.post("/events/{event_id}/reserve")
def reserve_seat(event_id: int, body: ReserveBody) -> JSONResponse:
    with pool.connection() as conn:
        outcome = reserve(conn, MODES["strategy"], event_id, body.student)
    return JSONResponse({"result": outcome.value}, status_code=STATUS[outcome])


@app.get("/events/{event_id}")
def event(event_id: int) -> JSONResponse:
    with pool.connection() as conn:
        state = shopdb.state(conn, event_id)
    if state is None:
        return JSONResponse({"error": "no such event"}, status_code=404)
    return JSONResponse({"capacity": state.capacity, "taken": state.sold})


# -- payments -------------------------------------------------------------------------------


class PaymentBody(BaseModel):
    order: int
    amount: int


@app.post("/payments")
def take_payment(
    body: PaymentBody, idempotency_key: str | None = Header(default=None)
) -> JSONResponse:
    if not idempotency_key:
        return JSONResponse({"error": "Idempotency-Key header required"}, status_code=400)
    with pool.connection() as conn:
        charge, created = payments.pay(
            conn, MODES["payments"], idempotency_key, body.order, body.amount
        )
    return JSONResponse({"charge": charge}, status_code=201 if created else 200)


# -- wallet ---------------------------------------------------------------------------------


class TopupBody(BaseModel):
    amount: int


@app.post("/wallets/{wallet_id}/topup")
def topup(wallet_id: int, body: TopupBody) -> JSONResponse:
    with pool.connection() as conn:
        balance = wallet.topup(conn, MODES["wallet"], wallet_id, body.amount)
    if balance is None:
        return JSONResponse({"error": "no such wallet"}, status_code=404)
    return JSONResponse({"balance": balance})


@app.post("/wallets/{wallet_id}/cashback")
def pay_cashback(wallet_id: int) -> JSONResponse:
    with pool.connection() as conn:
        paid = cashback.cashback(conn, MODES["cashback"], wallet_id)
    if paid is None:
        return JSONResponse({"error": "no such wallet"}, status_code=404)
    return JSONResponse({"cashback": paid[0], "balance": paid[1]})


# -- orders ---------------------------------------------------------------------------------


def _order_reply(done: bool | None, status: str) -> JSONResponse:
    if done is None:
        return JSONResponse({"error": "no such order"}, status_code=404)
    if not done:
        return JSONResponse({"error": "order is not pending"}, status_code=409)
    return JSONResponse({"status": status})


@app.post("/orders/{order_id}/pay")
def pay_order(order_id: int) -> JSONResponse:
    with pool.connection() as conn:
        return _order_reply(orders.pay(conn, MODES["orders"], order_id), "paid")


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int) -> JSONResponse:
    with pool.connection() as conn:
        return _order_reply(orders.cancel(conn, MODES["orders"], order_id), "cancelled")
