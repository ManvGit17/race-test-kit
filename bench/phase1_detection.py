"""Run the Phase 1 reference tests many times and count how often the lost update is caught.

    docker compose up -d --wait
    TEST_PG_DSN=postgresql://test:test@127.0.0.1:15418/test uv run python bench/phase1_detection.py

Each run is a fresh pytest process running one test from ``tests/test_counter.py``:

- ``test_naive_counter_loses_updates``: passes only when the runner caught at least one lost
  update, so a run counts as caught when pytest exits 0.
- ``test_atomic_counter_never_loses_an_update``: the control. Any violation is a false alarm.

Both the share of test runs and the share of rounds are reported, because a race test is a
sample: "caught in 98 of 100 runs" and "violated in 950 of 1000 rounds" say different things.
Writes ``bench/results/phase1-detection.json``. Exits 1 if the naive test is caught in fewer
than 95 runs or the atomic control ever violates.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "bench" / "results"
TESTS = {
    "naive": "tests/test_counter.py::test_naive_counter_loses_updates",
    "atomic": "tests/test_counter.py::test_atomic_counter_never_loses_an_update",
}


def run_once(test: str, out: Path) -> dict[str, Any]:
    out.unlink(missing_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
        cwd=ROOT,
        env={**os.environ, "RACEKIT_BENCH_OUT": str(out)},
        capture_output=True,
        text=True,
    )
    record: dict[str, Any] = json.loads(out.read_text()) if out.exists() else {}
    record["exit_code"] = proc.returncode
    if not out.exists():
        record["output_tail"] = (proc.stdout + proc.stderr)[-1000:]
    return record


def server_version() -> str:
    import psycopg

    with psycopg.connect(os.environ["TEST_PG_DSN"]) as conn:
        row = conn.execute("SHOW server_version").fetchone()
    return str(row[0]) if row else "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100)
    args = parser.parse_args()
    if not os.environ.get("TEST_PG_DSN"):
        raise SystemExit("TEST_PG_DSN is not set; start a database with `docker compose up -d`")

    summary: dict[str, Any] = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "command": f"uv run python bench/phase1_detection.py --runs {args.runs}",
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "postgres": server_version(),
        },
        "results": {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "record.json"
        for name, test in TESTS.items():
            runs = []
            for n in range(1, args.runs + 1):
                record = run_once(test, out)
                runs.append(record)
                violated, total = record.get("violations", "?"), record.get("rounds", "?")
                print(
                    f"{name} run {n}: exit {record['exit_code']},"
                    f" {violated} of {total} rounds violated"
                )
            rounds = sum(r.get("rounds", 0) for r in runs)
            violated = sum(r.get("violations", 0) for r in runs)
            spreads = sorted(s for r in runs for s in r.get("spread_ms", []))
            summary["results"][name] = {
                "test": test,
                "runs": len(runs),
                "runs_passed": sum(r["exit_code"] == 0 for r in runs),
                "rounds": rounds,
                "rounds_violated": violated,
                "call_errors": sum(r.get("errors", 0) for r in runs),
                "spread_ms_median": spreads[len(spreads) // 2] if spreads else None,
                "spread_ms_max": spreads[-1] if spreads else None,
                "per_run": runs,
            }

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "phase1-detection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    naive, atomic = summary["results"]["naive"], summary["results"]["atomic"]
    print(
        f"\nnaive: caught in {naive['runs_passed']} of {naive['runs']} test runs;"
        f" {naive['rounds_violated']} of {naive['rounds']} rounds lost an update"
    )
    print(
        f"atomic (control): {atomic['runs_passed']} of {atomic['runs']} test runs passed;"
        f" {atomic['rounds_violated']} of {atomic['rounds']} rounds violated"
    )
    print(
        f"start spread: median {naive['spread_ms_median']} ms, worst {naive['spread_ms_max']} ms"
        " (naive runs)"
    )
    ok = naive["runs_passed"] >= 0.95 * naive["runs"] and atomic["rounds_violated"] == 0
    return 0 if ok and atomic["runs_passed"] == atomic["runs"] else 1


if __name__ == "__main__":
    sys.exit(main())
