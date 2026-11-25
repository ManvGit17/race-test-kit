"""How far apart do N clients leave the starting gate on this machine, per backend?

    uv run python bench/spread.py

Runs ``racekit.run`` (threads) and ``racekit.arun`` (asyncio) with a call that does nothing,
so the spread is the gate's own release cost: for threads, Python waking N threads one after
another, each needing the GIL; for asyncio, the event loop resuming N tasks in turn. No server,
no database. Writes ``bench/results/spread.json``. These numbers back ADRs 0002 and 0007; they
depend on the machine and are not for the README.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import racekit

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = (2, 10, 50, 100, 300)
ROUNDS = 30


async def _nothing(i: int) -> None:
    return None


def _measure(backend: str, clients: int) -> racekit.RunResult:
    if backend == "threads":
        return racekit.run(lambda i: None, clients=clients, rounds=ROUNDS, seed=1)
    return asyncio.run(racekit.arun(_nothing, clients=clients, rounds=ROUNDS, seed=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["threads", "asyncio", "both"], default="both")
    args = parser.parse_args()
    backends = ["threads", "asyncio"] if args.backend == "both" else [args.backend]

    rows: list[dict[str, Any]] = []
    for backend in backends:
        for clients in CLIENTS:
            spreads = sorted(r.spread_ms for r in _measure(backend, clients).rounds)
            rows.append(
                {
                    "backend": backend,
                    "clients": clients,
                    "rounds": ROUNDS,
                    "median_ms": round(statistics.median(spreads), 3),
                    "p90_ms": round(spreads[int(0.9 * (len(spreads) - 1))], 3),
                    "max_ms": round(spreads[-1], 3),
                }
            )
            r = rows[-1]
            print(
                f"{backend:>8} {clients:>4} clients: median {r['median_ms']:.3f} ms,"
                f" p90 {r['p90_ms']:.3f} ms, max {r['max_ms']:.3f} ms"
            )
    out = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": f"uv run python bench/spread.py --backend {args.backend}",
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
