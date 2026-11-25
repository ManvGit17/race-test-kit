"""Monthly cashback: 1% of last month's spending, added to the balance. ``SHOP_CASHBACK``:

Both first check the wallet is eligible (any purchase this year).

* ``read_modify_write`` then reads the balance, adds up last month's spending, and writes back
  the balance it read plus the cashback. **Broken on purpose**: a top-up that commits between
  that read and the write is overwritten and lost. Released together with a top-up, the
  cashback loses it only in some rounds, depending on which of the two reaches the row first
  and on how long the spending takes to add up, so load alone catches the bug only some of
  the time.
* ``atomic`` adds up the spending, then ``UPDATE ... SET balance = balance + cashback``.

Both call ``racekit.pg.pause_point(conn, "cashback:before_write")`` just before writing. It
does nothing unless ``RACEKIT_PAUSE_POINTS=1``; a test can then hold the request there and
send the top-up into the window every time.
"""

from __future__ import annotations

from typing import Any

import psycopg

from racekit.pg import pause_point

Conn = psycopg.Connection[Any]

MODES = ("read_modify_write", "atomic")
PAUSE = "cashback:before_write"

_ELIGIBLE = (
    "SELECT EXISTS (SELECT 1 FROM shop_wallet_history"
    " WHERE wallet_id = %s AND amount < 0 AND at >= now() - interval '1 year')"
)
_SPENT = (
    "SELECT coalesce(sum(-amount), 0) FROM shop_wallet_history"
    " WHERE wallet_id = %s AND amount < 0 AND at >= now() - interval '1 month'"
)


def cashback(conn: Conn, mode: str, wallet_id: int) -> tuple[int, int] | None:
    """Pay this month's cashback. Returns (cashback, new balance), or None if no wallet."""
    with conn.transaction():
        found = conn.execute(_ELIGIBLE, (wallet_id,)).fetchone()
        eligible = bool(found and found[0])
        if mode == "read_modify_write":
            row = conn.execute(
                "SELECT balance FROM shop_wallets WHERE id = %s", (wallet_id,)
            ).fetchone()
            if row is None:
                return None
            back = _cashback(conn, wallet_id) if eligible else 0
            pause_point(conn, PAUSE)
            new = int(row[0]) + back  # the balance read before the spending was summed: the bug
            conn.execute("UPDATE shop_wallets SET balance = %s WHERE id = %s", (new, wallet_id))
            return back, new
        back = _cashback(conn, wallet_id) if eligible else 0
        pause_point(conn, PAUSE)
        updated = conn.execute(
            "UPDATE shop_wallets SET balance = balance + %s WHERE id = %s RETURNING balance",
            (back, wallet_id),
        ).fetchone()
        return None if updated is None else (back, int(updated[0]))


def _cashback(conn: Conn, wallet_id: int) -> int:
    """1% of last month's spending."""
    spent = conn.execute(_SPENT, (wallet_id,)).fetchone()
    return int(spent[0]) // 100 if spent else 0
