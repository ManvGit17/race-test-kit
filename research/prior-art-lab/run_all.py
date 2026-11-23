"""Run every probe against the lab app for many rounds and write the results.

    docker compose up -d --wait        # in this folder
    uv run --no-project --python 3.13 python run_all.py --label wide --rounds 20
    uv run --no-project --python 3.13 python run_all.py --label pair --clients 2 --seats 1 --rounds 40

Each probe runs in its own throwaway environment (``uv run --isolated --with ...``) holding
only that tool, because pytest loads every plugin it finds installed.

For every round: reset the database, run the probe once, then read the database. Two
verdicts are recorded per round:

* ``oversold``: the database holds more reservations than seats. This is the ground truth:
  the race really happened in that round.
* ``tool_failed``: the probe's own test went red (pytest exit code 1). Only probes that can
  express the invariant can go red because of it.

Output: ``results/<label>/<probe>.json`` per probe and ``results/<label>/summary.md``.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
PY = "3.13"

BASE = ["pytest==9.2.0", "httpx==0.28.1"]
APP = ["fastapi==0.165.0", "uvicorn==0.54.0", "psycopg[binary]==3.3.9", "psycopg-pool==3.3.3"]

SCHEMATHESIS = ["schemathesis", "run", f"{URL}/openapi.json", "-w", "8", "-n", "100"]


def pytest_cmd(file: str) -> list[str]:
    return ["pytest", "-q", "-p", "no:cacheprovider", file]


# name: (command, extra packages, strategy the app runs, most rounds worth running)
# Hypothesis and Schemathesis run many requests per round, so a few rounds are enough.
PROBES: dict[str, tuple[list[str], list[str], str, int | None]] = {
    "threadpool": (pytest_cmd("probe_threadpool.py"), [], "naive", None),
    "barrier": (pytest_cmd("probe_barrier.py"), [], "naive", None),
    "pytest-race": (pytest_cmd("probe_pytest_race.py"), ["pytest-race==0.2.0"], "naive", None),
    "pytest-together": (
        pytest_cmd("probe_pytest_together.py"),
        ["pytest-together==0.1.0"],
        "naive",
        None,
    ),
    "pytest-run-parallel": (
        pytest_cmd("probe_run_parallel.py"),
        ["pytest-run-parallel==0.10.0"],
        "naive",
        None,
    ),
    "pytest-asyncio-concurrent": (
        pytest_cmd("probe_asyncio_concurrent.py"),
        ["pytest-asyncio-concurrent==0.5.2"],
        "naive",
        None,
    ),
    "pytest-asyncio-concurrent-parametrize": (
        pytest_cmd("probe_asyncio_concurrent_parametrize.py"),
        ["pytest-asyncio-concurrent==0.5.2"],
        "naive",
        3,
    ),
    "hypothesis-stateful": (
        pytest_cmd("probe_hypothesis.py"),
        ["hypothesis==6.170.17"],
        "naive",
        5,
    ),
    # Fuzzes the one reserve operation with 8 workers; the check comes from st_hooks.py.
    "schemathesis": ([*SCHEMATHESIS, "-c", "never_oversold"], ["schemathesis==4.33.4"], "naive", 5),
    # The same barrier start against the correct strategy: must never oversell or go red.
    "barrier-vs-row_lock": (pytest_cmd("probe_barrier.py"), [], "row_lock", None),
}


def uv_run(packages: list[str]) -> list[str]:
    cmd = ["uv", "run", "--no-project", "--isolated", "--quiet", "--python", PY]
    for p in packages:
        cmd += ["--with", p]
    return cmd


def http(method: str, path: str) -> Any:
    req = urllib.request.Request(URL + path, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def start_app(strategy: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, "LAB_STRATEGY": strategy}
    cmd = [*uv_run(APP), "uvicorn", "labapp:app", "--port", str(PORT), "--log-level", "warning"]
    proc = subprocess.Popen(cmd, cwd=HERE, env=env)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit("the lab app exited during startup")
        try:
            http("GET", "/health")
            return proc
        except OSError:
            time.sleep(0.5)
    raise SystemExit("the lab app did not start in 120 s")


def stop_app(proc: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    proc.wait(timeout=30)


def installed_versions(packages: list[str]) -> dict[str, str]:
    names = [p.split("==")[0].split("[")[0] for p in packages]
    code = (
        "import importlib.metadata as m, json, platform, sys;"
        "v = {n: m.version(n) for n in sys.argv[1:]};"
        "v['python'] = platform.python_version();"
        "v['platform'] = platform.platform();"
        "print(json.dumps(v))"
    )
    out = subprocess.run(
        [*uv_run(packages), "python", "-c", code, *names], capture_output=True, text=True
    )
    return json.loads(out.stdout) if out.returncode == 0 else {"error": out.stderr[-500:]}


def run_probe(name: str, rounds: int, clients: int, seats: int) -> dict[str, Any]:
    command, extra, strategy, most = PROBES[name]
    rounds = min(rounds, most or rounds)
    packages = BASE + extra
    out_file = RESULTS / f"{name}.round.json"
    rows = []
    for n in range(1, rounds + 1):
        http("POST", f"/admin/reset?capacity={seats}")
        out_file.unlink(missing_ok=True)
        env = {
            **os.environ,
            "LAB_URL": URL,
            "LAB_CLIENTS": str(clients),
            "LAB_SEATS": str(seats),
            "LAB_OUT": str(out_file),
            "SCHEMATHESIS_HOOKS": "st_hooks",
            "PYTHONUTF8": "1",  # Schemathesis prints characters the Windows console code page lacks
        }
        t0 = time.monotonic()
        proc = subprocess.run(
            [*uv_run(packages), *command],
            cwd=HERE / "probes",
            env=env,
            capture_output=True,
            text=True,
        )
        seconds = time.monotonic() - t0
        state = http("GET", "/admin/state")
        probe = json.loads(out_file.read_text()) if out_file.exists() else {}
        row = {
            "round": n,
            "exit_code": proc.returncode,
            "tool_failed": proc.returncode == 1,
            "oversold": state["taken"] > seats,
            "taken": state["taken"],
            "requests_seen_by_server": state["requests"],
            "server_spread_ms": state["server_spread_ms"],
            "seconds": round(seconds, 2),
            **probe,
        }
        if proc.returncode not in (0, 1):
            row["error_tail"] = (proc.stdout + proc.stderr)[-1500:]
        elif proc.returncode == 1:
            # Keep the line that says why the test failed, and sort it into one of three.
            lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(("E ", "FAILED"))]
            row["failure"] = lines[:3]
            text = " | ".join(lines)
            if "NotConcurrent" in text:
                row["red_reason"] = "not_overlapped"
            elif ("assert" in text and "<=" in text) or "oversold" in text:
                row["red_reason"] = "invariant"
            else:
                row["red_reason"] = "tool_error"
        rows.append(row)
        print(
            f"  {name} round {n}: exit {proc.returncode}, taken {state['taken']}/{seats},"
            f" server spread {fmt(state['server_spread_ms'])} ms"
        )
    out_file.unlink(missing_ok=True)
    return {
        "probe": name,
        "command": command,
        "strategy": strategy,
        "clients": clients,
        "seats": seats,
        "rounds": rounds,
        "versions": installed_versions(packages),
        "rows": rows,
    }


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def median(values: list[float | None]) -> float | None:
    real = [v for v in values if v is not None]
    return statistics.median(real) if real else None


def summary(results: list[dict[str, Any]], args: argparse.Namespace) -> str:
    lines = [
        "# Prior-art lab results",
        "",
        f"Command: `uv run --no-project --python {PY} python run_all.py"
        f" --rounds {args.rounds} --clients {args.clients} --seats {args.seats}"
        f" --label {args.label}`",
        "",
        "| probe | strategy | rounds | oversold (database) | red: invariant"
        " | red: refused, not overlapped | red: tool error | median server spread ms"
        " | median client spread ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rows = r["rows"]
        oversold = sum(x["oversold"] for x in rows)

        def red(reason: str) -> int:
            return sum(x.get("red_reason") == reason for x in rows)

        errors = red("tool_error") + sum(x["exit_code"] not in (0, 1) for x in rows)
        lines.append(
            f"| {r['probe']} | {r['strategy']} | {len(rows)} | {oversold}"
            f" | {red('invariant')} | {red('not_overlapped')} | {errors}"
            f" | {fmt(median([x['server_spread_ms'] for x in rows]))}"
            f" | {fmt(median([x.get('client_spread_ms') for x in rows]))} |"
        )
    lines += [
        "",
        "oversold: rounds where the database held more reservations than seats (the race"
        " really happened). red: rounds where the probe's own test failed, by reason.",
        "Versions per probe are in each `results/<label>/<probe>.json`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rounds", type=int, default=20)
    p.add_argument("--clients", type=int, default=50)
    p.add_argument("--seats", type=int, default=10)
    p.add_argument("--only", nargs="*", choices=list(PROBES), help="run only these probes")
    p.add_argument("--label", default="trial", help="results go to results/<label>/")
    args = p.parse_args()

    global RESULTS
    RESULTS = RESULTS / args.label
    RESULTS.mkdir(parents=True, exist_ok=True)
    names = args.only or list(PROBES)
    results = []
    for strategy in ("naive", "row_lock"):
        todo = [n for n in names if PROBES[n][2] == strategy]  # one app start per strategy
        if not todo:
            continue
        print(f"starting the lab app with strategy {strategy}")
        app = start_app(strategy)
        try:
            for name in todo:
                result = run_probe(name, args.rounds, args.clients, args.seats)
                (RESULTS / f"{name}.json").write_text(
                    json.dumps(result, indent=2), encoding="utf-8"
                )
                results.append(result)
        finally:
            stop_app(app)
    if not args.only:
        (RESULTS / "summary.md").write_text(summary(results, args), encoding="utf-8")
    print(summary(results, args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
