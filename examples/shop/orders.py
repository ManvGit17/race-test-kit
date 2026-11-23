"""Paying or cancelling an order, but not both (the interleave scenario). ``SHOP_ORDERS``:

* ``check_then_act`` reads the status; if it is ``pending``, pay charges and marks the order
  paid, cancel marks it cancelled. **Broken on purpose**: a pay and a cancel arriving together
  both read ``pending`` and both succeed. The customer is told the order is cancelled, and is
  charged anyway (or told it is paid, after being told it is cancelled).
* ``guarded_update`` makes the status change itself the check: ``UPDATE ... SET status = ...
  WHERE status = 'pending' RETURNING id``. PostgreSQL re-checks the condition after a
  concurrent update commits, so exactly one of the two finds the order still pending.

Both answer 200 when the step happened and 409 when the order was no longer pending.
"""

from __future__ import annotations

from typing import Any

import psycopg

Conn = psycopg.Connection[Any]

MODES = ("check_then_act", "guarded_update")


def _move(conn: Conn, mode: str, order_id: int, new_status: str) -> bool | None:
    """Move a pending order to ``new_status``. ``None`` if the order does not exist."""
    if mode == "check_then_act":
        row = conn.execute("SELECT status FROM shop_orders WHERE id = %s", (order_id,)).fetchone()
        if row is None:
            return None
        if row[0] != "pending":
            return False
        # The other step may change the status after the read above: that is the bug.
        conn.execute("UPDATE shop_orders SET status = %s WHERE id = %s", (new_status, order_id))
        return True
    moved = conn.execute(
        "UPDATE shop_orders SET status = %s WHERE id = %s AND status = 'pending' RETURNING id",
        (new_status, order_id),
    ).fetchone()
    if moved is not None:
        return True
    exists = conn.execute("SELECT 1 FROM shop_orders WHERE id = %s", (order_id,)).fetchone()
    return None if exists is None else False


def pay(conn: Conn, mode: str, order_id: int) -> bool | None:
    """Charge the order and mark it paid. ``True`` if paid now, ``False`` if not pending."""
    with conn.transaction():
        moved = _move(conn, mode, order_id, "paid")
        if moved:
            conn.execute(
                "INSERT INTO shop_charges (order_id, amount)"
                " SELECT id, amount FROM shop_orders WHERE id = %s",
                (order_id,),
            )
        return moved


def cancel(conn: Conn, mode: str, order_id: int) -> bool | None:
    """Mark the order cancelled. ``True`` if cancelled now, ``False`` if not pending."""
    with conn.transaction():
        return _move(conn, mode, order_id, "cancelled")
