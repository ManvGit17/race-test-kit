"""Pause points: hold a request at a named line of the app's code, using PostgreSQL itself.

A race that load hits only sometimes needs one exact order of events, for example "the top-up
commits while the cashback job is between its read and its write". Pause points make that
order happen every time:

1. **In the app**, one line where the window is: ``pause_point(conn, "cashback:before_write")``.
   It does nothing unless ``RACEKIT_PAUSE_POINTS=1`` is set in the app's environment, so
   production pays nothing. When enabled, it takes and at once releases a PostgreSQL advisory
   lock named after the point.
2. **In the test**, ``PausePoints(dsn).hold(name)`` takes that lock first, on the test's own
   connection. The app's request now blocks at the pause point. ``wait_until_paused`` watches
   ``pg_locks`` until it sees the request waiting; the test then sends the other request, and
   releasing the lock lets the first one finish.

Locks use the two-number form ``pg_advisory_lock(NAMESPACE, hashtext(name))``. The fixed first
number keeps them apart from any advisory locks the app takes itself.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

#: First key of every pause-point lock: the bytes "RACE".
NAMESPACE = 0x52414345
#: Pause points only act when this is "1" in the app's environment.
ENV = "RACEKIT_PAUSE_POINTS"

_LOCK = "SELECT pg_advisory_lock(%s, hashtext(%s))"
_UNLOCK = "SELECT pg_advisory_unlock(%s, hashtext(%s))"
# A two-key advisory lock shows in pg_locks as classid = key 1, objid = key 2 (as an unsigned
# oid) and objsubid = 2. hashtext() is signed, hence the mask.
_WAITING = (
    "SELECT count(*) FROM pg_locks"
    " WHERE locktype = 'advisory' AND NOT granted AND objsubid = 2"
    " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
    " AND classid = %s::bigint::oid"
    " AND objid = (hashtext(%s)::bigint & 4294967295)::oid"
)


class PausePointNotReached(RuntimeError):
    """No request reached the pause point in time."""


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def pause_point(conn: Any, name: str) -> None:
    """Wait here while a test holds the pause point ``name``. A no-op unless enabled.

    ``conn`` is the app's psycopg connection (any object with ``execute`` works). The lock is
    taken and released at once, so with nobody holding it, it only costs two round trips.
    """
    if not enabled():
        return
    conn.execute(_LOCK, (NAMESPACE, name))
    conn.execute(_UNLOCK, (NAMESPACE, name))


class Held:
    """A pause point the test is holding. Requests reaching it wait until it is released."""

    def __init__(self, conn: Any, name: str) -> None:
        self._conn = conn
        self.name = name

    def waiting(self) -> int:
        """How many sessions are blocked at this pause point right now."""
        row = self._conn.execute(_WAITING, (NAMESPACE, self.name)).fetchone()
        return int(row[0])

    def wait_until_paused(self, timeout: float = 10.0, count: int = 1) -> None:
        """Block until ``count`` requests are waiting here; raise if that takes too long."""
        deadline = time.monotonic() + timeout
        while self.waiting() < count:
            if time.monotonic() > deadline:
                raise PausePointNotReached(
                    f"no request reached pause point {self.name!r} within {timeout:g} s;"
                    f" is {ENV}=1 set for the app, and does the code path call it?"
                )
            time.sleep(0.002)


class PausePoints:
    """The test side: hold pause points on a connection of its own."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def hold(self, name: str) -> Iterator[Held]:
        import psycopg  # optional dependency: pip install pytest-racekit[pg]

        conn = psycopg.connect(self.dsn, autocommit=True)
        try:
            conn.execute(_LOCK, (NAMESPACE, name))
            try:
                yield Held(conn, name)
            finally:
                conn.execute(_UNLOCK, (NAMESPACE, name))
        finally:
            conn.close()
