"""How far apart do N threads leave the starting gate on this machine?

    uv run python bench/spread.py

Runs ``racekit.run`` with a call that does nothing, so the spread is the gate's own release
cost: Python waking N threads one after another, each needing the GIL. No server, no
database. Writes ``bench/results/spread.json``. These numbers back ADR 0002; they depend on
the machine and are not for the README.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import racekit

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = (2, 10, 50, 100, 300)
ROUNDS = 30


def main() -> int:
    rows = []
    for clients in CLIENTS:
        result = racekit.run(lambda i: None, clients=clients, rounds=ROUNDS, seed=1)
        spreads = sorted(r.spread_ms for r in result.rounds)
        rows.append(
            {
                "clients": clients,
                "rounds": ROUNDS,
                "median_ms": round(statistics.median(spreads), 3),
                "p90_ms": round(spreads[int(0.9 * (len(spreads) - 1))], 3),
                "max_ms": round(spreads[-1], 3),
            }
        )
        print(
            f"{clients:>4} clients: median {rows[-1]['median_ms']:.2f} ms,"
            f" p90 {rows[-1]['p90_ms']:.2f} ms, max {rows[-1]['max_ms']:.2f} ms"
        )
    out = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": "uv run python bench/spread.py",
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
            "logical_cpus": os.cpu_count(),
        },
        "rows": rows,
    }
    (ROOT / "bench" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "bench" / "results" / "spread.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
