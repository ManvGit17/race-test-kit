"""Load alone against pause points: how often does the cashback's lost top-up get caught?

    docker compose up -d --wait
    TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test uv run python bench/phase5_forcing.py

PLAN.md's Phase 5 check: a lost-update test that fails about half the time by load alone must
fail every time with pause points. One "run of the test" is a fresh call of the harness race,
with fresh clients: by load alone, ``--load-rounds`` rounds of the cashback racing a top-up
(2 by default, which made the test fail in about 40% of runs while calibrating); with pause
points, a single round.
Each mode runs ``--runs`` times against the broken cashback and against the fixed one, and the
load-alone runs are also reported in batches of 10 to show how much the share moves.
Writes ``bench/results/phase5-forcing.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "shop"))

from harness import cashback_race, forced_cashback_race, serve  # noqa: E402

PURCHASES = 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--load-rounds", type=int, default=2)
    args = parser.parse_args()
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        raise SystemExit("TEST_PG_DSN is not set; start a database with `docker compose up -d`")

    results: dict[str, Any] = {}
    for version in ("read_modify_write", "atomic"):
        modes = {"wallet": "atomic", "cashback": version}
        for forced in (False, True):
            caught: list[bool] = []
            rounds = 1 if forced else args.load_rounds
            rounds_violated = 0
            with serve(dsn, modes=modes, pause_points=forced) as url:
                for _ in range(args.runs):
                    race = forced_cashback_race if forced else cashback_race
                    result = race(url, dsn, purchases=PURCHASES, rounds=rounds)
                    caught.append(result.violations > 0)
                    rounds_violated += result.violations
            key = f"{version}/{'pause points' if forced else 'load alone'}"
            batches = [sum(caught[i : i + 10]) for i in range(0, len(caught), 10)]
            results[key] = {
                "rounds_per_run": rounds,
                "rounds_violated": rounds_violated,
                "runs": len(caught),
                "runs_failed": sum(caught),
                "failed_per_batch_of_10": batches,
            }
            print(
                f"{key:>34}: the test failed in {sum(caught)} of {len(caught)} runs;"
                f" per 10 runs {batches}; {rounds_violated} of {rounds * len(caught)} rounds"
            )

    out = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": (
            f"uv run python bench/phase5_forcing.py --runs {args.runs}"
            f" --load-rounds {args.load_rounds}"
        ),
        "scenario": f"cashback (history of {PURCHASES} purchases) against a top-up of 10;"
        f" {args.load_rounds} rounds per load-alone run, 1 per pause-point run; fresh clients"
        " each run",
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        "results": results,
    }
    (ROOT / "bench" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "bench" / "results" / "phase5-forcing.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    broken = results["read_modify_write/pause points"]
    fixed = [results["atomic/load alone"], results["atomic/pause points"]]
    ok = broken["runs_failed"] == broken["runs"] and all(f["runs_failed"] == 0 for f in fixed)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
