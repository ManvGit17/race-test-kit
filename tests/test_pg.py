"""racekit.pg against real PostgreSQL: snapshots, pause points and forced interleavings."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from racekit import pg

POINT = "test:between_read_and_write"


@pytest.fixture
def db(pg_dsn: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        yield conn


# -- snapshot --------------------------------------------------------------------------------


@pytest.fixture
def tables(db: psycopg.Connection[Any]) -> Iterator[None]:
    db.execute("DROP TABLE IF EXISTS snap_child, snap_parent")
    db.execute(
        "CREATE TABLE snap_parent (id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name text)"
    )
    db.execute("CREATE TABLE snap_child (id serial PRIMARY KEY, parent int REFERENCES snap_parent)")
    db.execute("INSERT INTO snap_parent (name) VALUES ('a'), ('b')")
    db.execute("INSERT INTO snap_child (parent) VALUES (1), (2), (2)")
    yield
    db.execute("DROP TABLE IF EXISTS snap_child, snap_parent")


def _rows(db: psycopg.Connection[Any]) -> tuple[list[Any], list[Any]]:
    parents = db.execute("SELECT * FROM snap_parent ORDER BY id").fetchall()
    children = db.execute("SELECT * FROM snap_child ORDER BY id").fetchall()
    return parents, children


@pytest.mark.usefixtures("tables")
def test_snapshot_restores_rows_across_foreign_keys(db: psycopg.Connection[Any]) -> None:
    before = _rows(db)
    with pg.Snapshot(db, ["snap_parent", "snap_child"]) as snap:
        for _ in range(3):
            db.execute("DELETE FROM snap_child WHERE parent = 2")
            db.execute("UPDATE snap_parent SET name = 'changed'")
            db.execute("INSERT INTO snap_parent (name) VALUES ('new')")
            assert _rows(db) != before
            snap.restore()
            assert _rows(db) == before
    left = db.execute("SELECT count(*) FROM pg_tables WHERE tablename LIKE 'racekit_snap_%'")
    assert left.fetchone() == (0,)


def test_snapshot_needs_a_table(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(ValueError, match="at least one table"):
        pg.Snapshot(db, [])


# -- pause points ----------------------------------------------------------------------------


def _pause_in_thread(dsn: str, done: threading.Event) -> threading.Thread:
    def body() -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            pg.pause_point(conn, POINT)
        done.set()

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def test_an_enabled_pause_point_waits_until_released(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(pg.ENV, "1")
    done = threading.Event()
    with pg.PausePoints(pg_dsn).hold(POINT) as held:
        thread = _pause_in_thread(pg_dsn, done)
        held.wait_until_paused(timeout=10)
        assert held.waiting() == 1
        time.sleep(0.1)
        assert not done.is_set()  # still held at the pause point
    thread.join(10)
    assert done.is_set()


def test_a_disabled_pause_point_does_nothing(pg_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(pg.ENV, raising=False)
    done = threading.Event()
    with pg.PausePoints(pg_dsn).hold(POINT) as held:
        thread = _pause_in_thread(pg_dsn, done)
        assert done.wait(10)  # finished although the test holds the lock
        assert held.waiting() == 0
    thread.join(10)


def test_waiting_for_a_pause_point_nobody_reaches_times_out(pg_dsn: str) -> None:
    with pg.PausePoints(pg_dsn).hold(POINT) as held, pytest.raises(pg.PausePointNotReached):
        held.wait_until_paused(timeout=0.2)


# -- force -----------------------------------------------------------------------------------


@pytest.fixture
def counter(db: psycopg.Connection[Any]) -> Iterator[None]:
    db.execute("DROP TABLE IF EXISTS pause_counter")
    db.execute("CREATE TABLE pause_counter (id int PRIMARY KEY, value int NOT NULL)")
    db.execute("INSERT INTO pause_counter VALUES (1, 0)")
    yield
    db.execute("DROP TABLE pause_counter")


def _read_modify_write(dsn: str) -> None:
    """The lost-update bug, with a pause point in its window."""
    with psycopg.connect(dsn) as conn, conn.transaction():
        row = conn.execute("SELECT value FROM pause_counter WHERE id = 1").fetchone()
        assert row is not None
        pg.pause_point(conn, POINT)
        conn.execute("UPDATE pause_counter SET value = %s WHERE id = 1", (row[0] + 1,))


def _atomic(dsn: str) -> None:
    """The fix, with the same pause point: forcing the order must not break it."""
    with psycopg.connect(dsn) as conn, conn.transaction():
        pg.pause_point(conn, POINT)
        conn.execute("UPDATE pause_counter SET value = value + 1 WHERE id = 1")


def _increment(dsn: str) -> None:
    """The other request. No pause point: it must run while the first one is held."""
    with psycopg.connect(dsn) as conn, conn.transaction():
        conn.execute("UPDATE pause_counter SET value = value + 1 WHERE id = 1")


@pytest.mark.usefixtures("counter")
@pytest.mark.parametrize(("first", "violations"), [(_read_modify_write, 5), (_atomic, 0)])
def test_force_makes_the_lost_update_happen_every_round(
    db: psycopg.Connection[Any],
    pg_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    first: Any,
    violations: int,
) -> None:
    monkeypatch.setenv(pg.ENV, "1")

    def check() -> None:
        row = db.execute("SELECT value FROM pause_counter").fetchone()
        assert row == (2,), f"two increments, counter is {row}"

    result = pg.force(
        lambda: first(pg_dsn),
        lambda: _increment(pg_dsn),
        at=POINT,
        dsn=pg_dsn,
        rounds=5,
        reset=lambda: db.execute("UPDATE pause_counter SET value = 0"),
        check=check,
        names=("first", "increment"),
    )
    assert result.violations == violations, result.report()
    assert result.steps == ["first", "increment"]
    assert all(r.errors == {} for r in result.rounds)


def test_force_fails_clearly_when_the_pause_point_is_never_reached(pg_dsn: str) -> None:
    with pytest.raises(pg.PausePointNotReached, match="never reached pause point"):
        pg.force(lambda: None, lambda: None, at=POINT, dsn=pg_dsn, timeout=0.2)
