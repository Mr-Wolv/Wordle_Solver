"""End-to-end coverage for the CLI and the analysis tools.

These exercise real dataflows that the rest of the suite leaves untested:
  * app/cli.py  — single-shot mode run as a real subprocess (boundary:
    argv -> pattern parse -> engine.update_state -> suggestions out).
  * tools/benchmark.py + tools/profiler.py — the user-facing analysis CLIs,
    run headless on a tiny sample so they don't depend on a display or take
    minutes. We assert they execute, emit their report, and exit 0.
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))


def _run_cli(args, timeout=120):
    return subprocess.run(
        [PY, "-m", "wordle_solver.app.cli", *args],
        cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=timeout,
    )


def test_cli_single_shot_runs_and_exits_zero():
    # crane with full-green pattern -> the engine should report crane as the
    # top/only answer and exit cleanly.
    res = _run_cli(["--guess", "crane", "--pattern", "22222"])
    assert res.returncode == 0, res.stderr
    assert "CRANE" in res.stdout.upper()


def test_cli_single_shot_unknown_word_exits_nonzero():
    # a word not in the list must be rejected (INPUT_ERROR path).
    res = _run_cli(["--guess", "zzzzz", "--pattern", "00000"])
    assert res.returncode != 0


def test_cli_single_shot_bad_pattern_exits_nonzero():
    res = _run_cli(["--guess", "crane", "--pattern", "2222"])  # too short
    assert res.returncode != 0


def test_benchmark_runs_headless():
    # tiny sample, sequential (no multiprocessing flakiness in CI), JSON out.
    res = subprocess.run(
        [PY, "-m", "wordle_solver.tools.benchmark",
         "--samples", "8", "--sequential", "--json"],
        cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=300,
    )
    assert res.returncode == 0, res.stderr
    assert '"accuracy"' in res.stdout or '"samples"' in res.stdout


def test_profiler_runs_headless():
    res = subprocess.run(
        [PY, "-m", "wordle_solver.tools.profiler", "--word", "crane", "--lines", "5"],
        cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, res.stderr
    assert "crane".upper() in res.stdout.upper()
