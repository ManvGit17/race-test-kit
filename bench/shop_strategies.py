"""Race the demo shop under each strategy and record how often each one oversells.

    docker compose up -d --wait
    TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test uv run python bench/shop_strategies.py

The same scenario as ``examples/shop/tests``: 50 students, 10 seats, released together, the
event reset in the database before each round and checked after. Each strategy runs
``--runs`` times ``--rounds`` rounds on its own server. Writes
``bench/results/shop-strategies.json``. Exits 1 if ``naive`` never oversells or a safe
strategy ever does.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "shop"))

from harness import reserve_race, serve  # noqa: E402
from strategies import STRATEGIES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--seats", type=int, default=10)
    args = parser.parse_args()
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        raise SystemExit("TEST_PG_DSN is not set; start a database with `docker compose up -d`")

    results: dict[str, Any] = {}
    for strategy in STRATEGIES:
        statuses: Counter[str] = Counter()
        sold: list[int] = []
        spreads: list[float] = []
        violations = errors = 0
        with serve(dsn, strategy) as url:
            for _ in range(args.runs):
                race = reserve_race(
                    url,
                    dsn,
                    strategy,
                    clients=args.clients,
                    seats=args.seats,
                    rounds=args.rounds,
                )
                violations += race.result.violations
                sold += race.sold
                for rnd in race.result.rounds:
                    statuses.update({str(k): v for k, v in rnd.statuses.items()})
                    errors += sum(rnd.errors.values())
                    spreads.append(rnd.spread_ms)
        rounds = args.runs * args.rounds
        results[strategy] = {
            "rounds": rounds,
            "rounds_oversold": violations,
            "rounds_sold_out": sum(s == args.seats for s in sold),
            "rounds_undersold": sum(s < args.seats for s in sold),
            "most_sold": max(sold),
            "statuses": dict(sorted(statuses.items())),
            "call_errors": errors,
            "spread_ms_median": round(statistics.median(spreads), 3),
            "spread_ms_max": round(max(spreads), 3),
        }
        r = results[strategy]
        print(
            f"{strategy:>13}: oversold in {r['rounds_oversold']} of {rounds} rounds"
            f" (most sold {r['most_sold']} of {args.seats}); sold out in"
            f" {r['rounds_sold_out']}; statuses {r['statuses']}"
        )

    out = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": (
            f"uv run python bench/shop_strategies.py --runs {args.runs} --rounds"
            f" {args.rounds} --clients {args.clients} --seats {args.seats}"
        ),
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        "results": results,
    }
    (ROOT / "bench" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "bench" / "results" / "shop-strategies.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    safe_ok = all(results[s]["rounds_oversold"] == 0 for s in STRATEGIES if s != "naive")
    return 0 if results["naive"]["rounds_oversold"] > 0 and safe_ok else 1


if __name__ == "__main__":
    sys.exit(main())
