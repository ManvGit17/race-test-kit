"""``racekit run FILE``: run race scenarios outside pytest.

    racekit run examples/shop/race_shop.py --rounds 50 --seed 7 -k oversell

Runs every function in FILE whose name starts with ``race_`` and that takes one argument, the
same ``race`` a pytest test gets as a fixture (``async def`` functions too). Prints each run's
report. Exit status: 0 if every function returned, 1 if any raised (a failed ``assert`` is the
usual way to say an invariant broke), 2 if FILE could not be loaded or has no scenarios.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from racekit.race import Race


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"racekit_scenarios_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))  # let the file import its neighbours, like pytest does
    spec.loader.exec_module(module)
    return module


def _scenarios(module: ModuleType, keyword: str | None) -> list[Callable[..., Any]]:
    return [
        value
        for name, value in vars(module).items()
        if name.startswith("race_")
        and inspect.isfunction(value)
        and (keyword is None or keyword in name)
    ]


def _where(exc: AssertionError) -> str:
    """Where the failed assert is, and its message's first line (the report follows anyway)."""
    frame = traceback.extract_tb(exc.__traceback__)[-1]
    place = f"{Path(frame.filename).name}:{frame.lineno}: {frame.line or 'assert'}"
    first = str(exc).splitlines()[0] if str(exc) else ""
    return f"{place} ({first})" if first else place


def _run_one(scenario: Callable[..., Any], race: Race) -> bool:
    try:
        if inspect.iscoroutinefunction(scenario):
            asyncio.run(scenario(race))
        else:
            scenario(race)
    except AssertionError as exc:
        print(f"FAIL {scenario.__name__}: {_where(exc)}")
        return False
    except Exception:
        print(f"ERROR {scenario.__name__}:")
        traceback.print_exc(file=sys.stdout)
        return False
    print(f"PASS {scenario.__name__}")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="racekit", description="Race testing for live services.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the race_* functions in a file")
    run.add_argument("file", type=Path)
    run.add_argument("-k", dest="keyword", help="only functions whose name contains this")
    run.add_argument("--rounds", type=int, help="rounds for runs that do not set their own")
    run.add_argument("--seed", type=int, help="seed for runs that do not set their own")
    args = parser.parse_args(argv)

    try:
        module = _load(args.file)
    except Exception:
        print(f"racekit: could not load {args.file}:")
        traceback.print_exc(file=sys.stdout)
        return 2
    scenarios = _scenarios(module, args.keyword)
    if not scenarios:
        print(f"racekit: no race_* functions in {args.file}")
        return 2

    failed = 0
    for scenario in scenarios:
        race = Race(rounds=args.rounds, seed=args.seed)
        if not _run_one(scenario, race):
            failed += 1
        print(race.report(), end="\n\n")
    print(f"racekit: {len(scenarios) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
