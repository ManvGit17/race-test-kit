"""Threads against asyncio on the real shop: how tight is the start with HTTP calls, and how
often is the naive oversell caught?

    docker compose up -d --wait
    TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test uv run python bench/backends.py

The same race for both backends: 50 students, 10 seats, warmed clients (``httpx.Client`` per
thread, ``httpx.AsyncClient`` per task), against the ``naive`` shop. Writes
``bench/results/backends.json``.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "shop"))

from harness import async_reserve_race, reserve_race, serve  # noqa: E402

import racekit  # noqa: E402


def _summary(result: racekit.RunResult) -> dict[str, Any]:
    spreads = [r.spread_ms for r in result.rounds]
    latencies = sorted(c.latency_ms for r in result.rounds for c in r.calls)
    return {
        "rounds": result.rounds_run,
        "rounds_oversold": result.violations,
        "spread_ms_median": round(statistics.median(spreads), 3),
        "spread_ms_max": round(max(spreads), 3),
        "latency_ms_p50": round(latencies[len(latencies) // 2], 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        raise SystemExit("TEST_PG_DSN is not set; start a database with `docker compose up -d`")

    results: dict[str, list[dict[str, Any]]] = {"threads": [], "asyncio": []}
    with serve(dsn, "naive") as url:
        for _ in range(args.runs):  # alternate, so drift on the machine hits both alike
            results["threads"].append(_summary(reserve_race(url, dsn, "naive").result))
            results["asyncio"].append(_summary(asyncio.run(async_reserve_race(url, dsn))))

    totals = {}
    for backend, runs in results.items():
        totals[backend] = {
            "rounds": sum(r["rounds"] for r in runs),
            "rounds_oversold": sum(r["rounds_oversold"] for r in runs),
            "spread_ms_median": round(statistics.median(r["spread_ms_median"] for r in runs), 3),
            "spread_ms_max": max(r["spread_ms_max"] for r in runs),
            "latency_ms_p50": round(statistics.median(r["latency_ms_p50"] for r in runs), 3),
        }
        t = totals[backend]
        print(
            f"{backend:>8}: oversold in {t['rounds_oversold']} of {t['rounds']} rounds;"
            f" start spread median {t['spread_ms_median']} ms, worst {t['spread_ms_max']} ms;"
            f" latency p50 {t['latency_ms_p50']} ms"
        )

    out = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": f"uv run python bench/backends.py --runs {args.runs}",
        "scenario": "50 students, 10 seats, naive strategy, 20 rounds per run",
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        "totals": totals,
        "per_run": results,
    }
    (ROOT / "bench" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "bench" / "results" / "backends.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
