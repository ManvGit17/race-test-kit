"""Run the three scenarios against the broken and the fixed shop, and record the rates.

    docker compose up -d --wait
    TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test uv run python bench/phase3_scenarios.py

The same races as ``examples/shop/tests/test_shop_scenarios.py``: one payment sent 5 times
(duplicate), 20 top-ups (lost_update), and a pay against a cancel on 5 orders (interleave).
Writes ``bench/results/phase3-scenarios.json``. Exits 1 if a broken version is never caught or
a fixed one is ever accused.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "shop"))

from harness import (  # noqa: E402
    duplicate_payment_race,
    pay_cancel_race,
    serve,
    topup_race,
)

import racekit  # noqa: E402

BUILDS = {
    "broken": {
        "payments": "check_then_insert",
        "wallet": "read_modify_write",
        "orders": "check_then_act",
    },
    "fixed": {"payments": "unique_key", "wallet": "atomic", "orders": "guarded_update"},
}
SCENARIOS: dict[str, tuple[str, Callable[..., racekit.RunResult], dict[str, int]]] = {
    "duplicate": ("payments", duplicate_payment_race, {"copies": 5}),
    "lost_update": ("wallet", topup_race, {"clients": 20}),
    "interleave": ("orders", pay_cancel_race, {"orders": 5}),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=100)
    args = parser.parse_args()
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        raise SystemExit("TEST_PG_DSN is not set; start a database with `docker compose up -d`")

    results: dict[str, Any] = {}
    for build, modes in BUILDS.items():
        with serve(dsn, modes=modes) as url:
            for name, (feature, race, size) in SCENARIOS.items():
                result = race(url, dsn, rounds=args.rounds, **size)
                statuses: Counter[str] = Counter()
                for rnd in result.rounds:
                    statuses.update({str(k): v for k, v in rnd.statuses.items()})
                key = f"{name}/{build}"
                results[key] = {
                    "version": modes[feature],
                    "size": size,
                    "rounds": result.rounds_run,
                    "rounds_violated": result.violations,
                    "statuses": dict(sorted(statuses.items())),
                    "call_errors": sum(sum(r.errors.values()) for r in result.rounds),
                    "spread_ms_median": round(
                        statistics.median(r.spread_ms for r in result.rounds), 3
                    ),
                    "first_violation": next(
                        (r.check_message for r in result.rounds if r.violated), None
                    ),
                }
                print(
                    f"{key:>20} ({modes[feature]}): violated in {result.violations} of"
                    f" {result.rounds_run} rounds; statuses {results[key]['statuses']}"
                )

    out = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": f"uv run python bench/phase3_scenarios.py --rounds {args.rounds}",
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        "results": results,
    }
    (ROOT / "bench" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "bench" / "results" / "phase3-scenarios.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    caught = all(results[f"{n}/broken"]["rounds_violated"] > 0 for n in SCENARIOS)
    clean = all(results[f"{n}/fixed"]["rounds_violated"] == 0 for n in SCENARIOS)
    return 0 if caught and clean else 1


if __name__ == "__main__":
    sys.exit(main())
