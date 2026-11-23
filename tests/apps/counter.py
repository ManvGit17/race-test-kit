"""A counter service for the runner's tests, backed by PostgreSQL.

    python tests/apps/counter.py --dsn postgresql://... --mode naive --key naive

Prints the port it listens on, then serves until killed. Endpoints:

- ``POST /incr`` adds one to the counter.
  ``--mode naive`` reads the value, then writes back what it read plus one, in one
  transaction. Two requests can read the same value; the second write then overwrites the
  first: a lost update. ``--mode atomic`` runs ``UPDATE ... SET value = value + 1``.
- ``POST /reset`` sets the counter to 0. ``GET /value`` returns it. ``GET /health``.

Standard library HTTP server on purpose: no framework to learn for a 60-line test fixture,
and it runs in its own process so it never shares the test process's GIL.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from psycopg_pool import ConnectionPool

pool: ConnectionPool[Any]
MODE = "naive"
KEY = "counter"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, so a warmed connection is reused

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"ok": True})
        elif self.path == "/value":
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT value FROM racekit_counter WHERE key = %s", (KEY,)
                ).fetchone()
            assert row is not None
            self._reply(200, {"value": row[0]})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/incr":
            with pool.connection() as conn:  # one transaction, committed at the end
                if MODE == "atomic":
                    conn.execute(
                        "UPDATE racekit_counter SET value = value + 1 WHERE key = %s", (KEY,)
                    )
                else:
                    row = conn.execute(
                        "SELECT value FROM racekit_counter WHERE key = %s", (KEY,)
                    ).fetchone()
                    assert row is not None
                    conn.execute(
                        "UPDATE racekit_counter SET value = %s WHERE key = %s", (row[0] + 1, KEY)
                    )
            self._reply(200, {"ok": True})
        elif self.path == "/reset":
            with pool.connection() as conn:
                conn.execute("UPDATE racekit_counter SET value = 0 WHERE key = %s", (KEY,))
            self._reply(200, {"value": 0})
        else:
            self._reply(404, {"error": "not found"})

    def _reply(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # keep test output quiet


def main() -> None:
    global pool, MODE, KEY
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--mode", choices=["naive", "atomic"], default="naive")
    parser.add_argument("--key", default="counter")
    args = parser.parse_args()
    MODE, KEY = args.mode, args.key

    pool = ConnectionPool(args.dsn, min_size=4, max_size=20, open=True)
    with pool.connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS racekit_counter (key text PRIMARY KEY, value int NOT NULL)"
        )
        conn.execute(
            "INSERT INTO racekit_counter (key, value) VALUES (%s, 0) ON CONFLICT DO NOTHING",
            (KEY,),
        )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
