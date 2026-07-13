#!/usr/bin/env python3
"""Safety-net monitor for the Wordle_Solver engineering audit.

Why this exists (user directive): the engineering-intelligence audit must
continue even if the Hermes model/connection drops (network blip, API
traffic, model failure). This script is run by a cron job on a schedule.
It is the LIGHTWEIGHT WATCHDOG that decides whether to keep working:

  1. Smoke-run the test suite (fast subset, excludes the multi-minute
     exhaustive gate).
  2. Census for orphaned game/dev_server processes (the matrix-mmap leak
     failure mode the architecture was built to prevent).
  3. If anything is RED -> it dispatches a fresh agent sub-task carrying the
     full ENGINEERING INTELLIGENCE DIRECTIVE to continue/finish the work.

It NEVER fabricates success: a failure is reported as a failure and the
sub-agent is asked to produce REAL fixes + REAL green output.

Run: python cron_monitor.py
Exit code 0 = healthy; non-zero = intervention needed (also prints JSON).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable


def _run(cmd, timeout=600):
    try:
        return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                               timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def smoke_tests():
    """Run the fast (exhaustive-excluded) suite. Return (passed, summary)."""
    res = _run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                "-m", "not exhaustive",
                "--ignore=tests/test_e2e_web.py",
                "--ignore=tests/test_workflows_web.py",
                "--ignore=tests/test_frozen_bundle.py"], timeout=900)
    if res is None:
        return False, "smoke suite timed out (>900s)"
    if res.returncode != 0:
        tail = "\n".join(res.stdout.strip().splitlines()[-12:])
        return False, f"smoke suite FAILED (rc={res.returncode}):\n{tail}"
    return True, "smoke suite green"


def census():
    """Return the process census dict (or None on error)."""
    res = _run([PY, "__census.py"], timeout=60)
    if res is None or res.returncode != 0:
        return None
    for line in res.stdout.splitlines():
        if line.startswith("CENSUS_JSON "):
            try:
                return json.loads(line.split("CENSUS_JSON ", 1)[1])
            except Exception:
                return None
    return None


def main():
    report = {"healthy": True, "steps": []}

    ok, msg = smoke_tests()
    report["steps"].append({"smoke": ok, "detail": msg})
    if not ok:
        report["healthy"] = False

    c = census()
    if c is None:
        report["steps"].append({"census": None, "detail": "census failed"})
    else:
        orphans = (c.get("dev_server", 0) or 0) + (c.get("game_exe", 0) or 0)
        report["steps"].append({"census": c, "orphans": orphans})
        if orphans > 0:
            report["healthy"] = False
            report["steps"][-1]["detail"] = (
                "ORPHANED game/dev processes detected -> matrix mmap leak")

    print(json.dumps(report, indent=2))
    if report["healthy"]:
        print("HEALTHY: repo engineering state is GREEN. No intervention needed.")
        return 0

    print("UNHEALTHY: dispatching engineering sub-agent to continue the audit.")
    # The sub-agent carries the full directive and must produce real fixes
    # + real green test output (it is told NOT to fabricate success).
    try:
        # Import lazily so the script works even if the tool package path
        # differs; fall back to a no-op if delegation isn't available.
        from hermes_tools import delegate_task  # type: ignore
        delegate_task(
            goal=(
                "The Wordle_Solver repo (D:\\Wordle_Solver) engineering audit "
                "is UNHEALTHY. A prior autonomous audit was interrupted. "
                "Continue the ENGINEERING INTELLIGENCE DIRECTIVE: make every "
                "test green, every flow intact, every exception handled, fix "
                "all correctness/reliability/leak defects. Run 'uv pytest' / "
                "the project's pytest suite as the source of truth; do NOT "
                "fabricate success. Kill any orphaned dev_server/game EXE "
                "processes holding wordle_full_matrix.npy open. Then run the "
                "full 6-mode x 2315-word exhaustive gate and report real "
                "results. Work autonomously, commit coherent batches locally, "
                "but do NOT push."
            ),
            context=json.dumps(report),
        )
    except Exception as e:  # pragma: no cover - best effort watchdog
        print(f"delegate unavailable: {e}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
