"""Does installing the package give pytest the ``race`` fixture, with no conftest at all?

    uv run python scripts/plugin_install_check.py

Builds the wheel, installs it with pytest into a brand-new virtual environment in a temporary
directory, writes a test file there (no conftest, no pytest configuration), and runs it with
``--race-rounds 7``. The tests check that the fixture exists, that the option and the marker
apply, and that the ``racekit`` command was installed. Exits 0 only if all of that holds.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST = "pytest==9.2.0"

TEST_FILE = """
import sys
from pathlib import Path

import pytest
import racekit


def test_fixture_comes_from_the_installed_package(race):
    assert isinstance(race, racekit.Race)
    assert race.run(lambda i: i, clients=2).rounds_run == 7  # from --race-rounds 7


@pytest.mark.race(rounds=3, seed=11)
def test_marker_beats_the_option(race):
    result = race.run(lambda i: None, clients=2)
    assert (result.rounds_run, result.seed) == (3, 11)


def test_cli_was_installed_into_this_environment():
    # Look next to this interpreter only: PATH may also hold another environment's racekit.
    scripts = Path(sys.executable).parent
    assert (scripts / "racekit").exists() or (scripts / "racekit.exe").exists()
"""


def run(*cmd: str | Path, cwd: Path = ROOT) -> str:
    print("$", " ".join(str(c) for c in cmd))
    done = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
    print(done.stdout + done.stderr)
    if done.returncode != 0:
        raise SystemExit(f"failed with exit code {done.returncode}")
    return done.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="racekit-install-") as tmp:
        work = Path(tmp)
        run("uv", "build", "--wheel", "--out-dir", work / "dist")
        wheel = next((work / "dist").glob("*.whl"))
        venv = work / "venv"
        run("uv", "venv", venv, "--python", f"{sys.version_info.major}.{sys.version_info.minor}")
        bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
        python = bindir / ("python.exe" if sys.platform == "win32" else "python")
        run("uv", "pip", "install", "--python", python, wheel, PYTEST)

        project = work / "project"
        project.mkdir()
        (project / "test_installed.py").write_text(TEST_FILE, encoding="utf-8")
        assert not any(project.glob("conftest.py"))
        out = run(
            python,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--race-rounds",
            "7",
            "-v",
            cwd=project,
        )
        if "3 passed" not in out:
            raise SystemExit("expected 3 passed")
    print("plugin install check: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
