"""Table snapshot and restore, for resetting a database between rounds.

    snap = Snapshot(conn, ["shop_wallets", "shop_wallet_history"])
    snap.take()                       # copy the tables as they are now
    racekit.run(..., reset=snap.restore)
    snap.drop()

``take()`` copies each table into an unlogged ``racekit_snap_<table>``. ``restore()`` empties
all the listed tables in one ``TRUNCATE`` (so foreign keys *between* them are no obstacle) and
reinserts the rows in the order listed: list parent tables before the tables that refer to
them. Everything happens in one transaction.

Not restored: sequences keep counting, so ids made after a restore differ from the first run's.
Tables are named without a schema and found through ``search_path``.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import Any


class Snapshot:
    def __init__(self, conn: Any, tables: Sequence[str]) -> None:
        if not tables:
            raise ValueError("Snapshot needs at least one table")
        self.conn = conn
        self.tables = list(tables)

    def _ids(self, table: str) -> tuple[Any, Any]:
        from psycopg import sql

        return sql.Identifier(table), sql.Identifier(f"racekit_snap_{table}")

    def take(self) -> None:
        from psycopg import sql

        with self.conn.transaction():
            for table in self.tables:
                live, copy = self._ids(table)
                self.conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(copy))
                self.conn.execute(
                    sql.SQL("CREATE UNLOGGED TABLE {} AS SELECT * FROM {}").format(copy, live)
                )

    def restore(self) -> None:
        from psycopg import sql

        with self.conn.transaction():
            everything = sql.SQL(", ").join(self._ids(t)[0] for t in self.tables)
            self.conn.execute(sql.SQL("TRUNCATE {}").format(everything))
            for table in self.tables:
                live, copy = self._ids(table)
                # OVERRIDING SYSTEM VALUE: put back the saved ids even in GENERATED ALWAYS columns.
                self.conn.execute(
                    sql.SQL("INSERT INTO {} OVERRIDING SYSTEM VALUE SELECT * FROM {}").format(
                        live, copy
                    )
                )

    def drop(self) -> None:
        from psycopg import sql

        with self.conn.transaction():
            for table in self.tables:
                self.conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(self._ids(table)[1]))

    def __enter__(self) -> Snapshot:
        self.take()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.drop()
