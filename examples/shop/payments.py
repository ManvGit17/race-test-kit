"""Taking a payment once per ``Idempotency-Key`` (the duplicate scenario). ``SHOP_PAYMENTS``:

* ``check_then_insert`` looks for a charge with the key, and inserts one if there is none.
  **Broken on purpose**: copies of one request arriving together all look, all find nothing,
  and all charge.
* ``unique_key`` claims the key first: ``INSERT ... ON CONFLICT DO NOTHING`` into a table
  whose primary key is the key. Only one transaction can insert it; the others wait for it to
  commit, see the conflict, and return the charge it made.

Both answer 201 with the charge id when they charge, 200 with the same id for a replay.
"""

from __future__ import annotations

from typing import Any

import psycopg

Conn = psycopg.Connection[Any]

MODES = ("check_then_insert", "unique_key")


def _charge(conn: Conn, order_id: int, amount: int, key: str) -> int:
    row = conn.execute(
        "INSERT INTO shop_charges (order_id, amount, idempotency_key) VALUES (%s, %s, %s)"
        " RETURNING id",
        (order_id, amount, key),
    ).fetchone()
    assert row is not None
    return int(row[0])


def pay(conn: Conn, mode: str, key: str, order_id: int, amount: int) -> tuple[int, bool]:
    """Charge once for ``key``. Returns the charge id and whether this call made it."""
    with conn.transaction():
        if mode == "check_then_insert":
            found = conn.execute(
                "SELECT id FROM shop_charges WHERE idempotency_key = %s ORDER BY id LIMIT 1",
                (key,),
            ).fetchone()
            if found is not None:
                return int(found[0]), False
            # Another copy may have inserted since the look-up above: that is the bug.
            return _charge(conn, order_id, amount, key), True

        claimed = conn.execute(
            "INSERT INTO shop_idempotency_keys (key) VALUES (%s)"
            " ON CONFLICT (key) DO NOTHING RETURNING key",
            (key,),
        ).fetchone()
        if claimed is None:
            # The key's owner has committed by now (the insert waited for it), so its charge
            # id is there to return.
            row = conn.execute(
                "SELECT charge_id FROM shop_idempotency_keys WHERE key = %s", (key,)
            ).fetchone()
            assert row is not None and row[0] is not None
            return int(row[0]), False
        charge_id = _charge(conn, order_id, amount, key)
        conn.execute(
            "UPDATE shop_idempotency_keys SET charge_id = %s WHERE key = %s", (charge_id, key)
        )
        return charge_id, True
