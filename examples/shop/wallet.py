"""Topping up a balance (the lost_update scenario). ``SHOP_WALLET``:

* ``read_modify_write`` reads the balance, adds in Python, writes the result back.
  **Broken on purpose**: two top-ups read the same balance; the second write replaces the
  first, and one top-up is lost although both were acknowledged.
* ``atomic`` runs ``UPDATE ... SET balance = balance + amount``: PostgreSQL re-reads the row
  after any concurrent update commits, so every addition counts.
"""

from __future__ import annotations

from typing import Any

import psycopg

Conn = psycopg.Connection[Any]

MODES = ("read_modify_write", "atomic")


def topup(conn: Conn, mode: str, wallet_id: int, amount: int) -> int | None:
    """Add ``amount``; return the new balance, or ``None`` if there is no such wallet."""
    with conn.transaction():
        if mode == "read_modify_write":
            row = conn.execute(
                "SELECT balance FROM shop_wallets WHERE id = %s", (wallet_id,)
            ).fetchone()
            if row is None:
                return None
            new = int(row[0]) + amount
            conn.execute("UPDATE shop_wallets SET balance = %s WHERE id = %s", (new, wallet_id))
            return new
        row = conn.execute(
            "UPDATE shop_wallets SET balance = balance + %s WHERE id = %s RETURNING balance",
            (amount, wallet_id),
        ).fetchone()
        return None if row is None else int(row[0])
