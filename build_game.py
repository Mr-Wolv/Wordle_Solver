#!/usr/bin/env python3
"""Build the Wordle Strat-Console desktop app into a one-folder EXE.

Usage:
    python build_game.py            # clean build -> dist/Wordle-Strat-Console/
    python build_game.py --no-clean # keep PyInstaller's build/ work dir

This script ONLY builds. It never launches the game, so it cannot leave a
lingering process or spawn a fork-bomb. The frozen EXE runs its backend
in-process (desktop_app._is_frozen) and self-terminates on window close.

Requires the dev venv that has pyinstaller + the project deps installed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "desktop_app.spec")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
# PyInstaller writes its transient work dir next to cwd; we clean it after.
BUILD_DIR = os.path.join(REPO_ROOT, "build")
# The spec also emits a duplicate dist next to itself if run from there;
# we run from REPO_ROOT so output lands in the canonical DIST_DIR, but we
# still scrub any stray copy the spec might leave behind.
STRAY_DIST = os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "dist")


def _rm(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Wordle Strat-Console EXE.")
    parser.add_argument(
        "--no-clean", action="store_true",
        help="keep PyInstaller's transient build/ work dir after building",
    )
    args = parser.parse_args()

    if not os.path.exists(SPEC):
        print(f"[build] ERROR: spec not found: {SPEC}", file=sys.stderr)
        return 1

    # start from a clean output slot so a stale binary can never be reused
    _rm(DIST_DIR)
    _rm(STRAY_DIST)

    print(f"[build] PyInstaller spec : {SPEC}")
    print(f"[build] output           : {DIST_DIR}/Wordle-Strat-Console/")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        SPEC,
        "--noconfirm",
        "--clean",
        f"--distpath={DIST_DIR}",
    ]
    print("[build] running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=REPO_ROOT)
    if rc != 0:
        print(f"[build] FAILED (pyinstaller exit {rc})", file=sys.stderr)
        return rc

    # tidy transient artifacts
    if not args.no_clean:
        _rm(BUILD_DIR)
    _rm(STRAY_DIST)

    exe = os.path.join(DIST_DIR, "Wordle-Strat-Console", "Wordle-Strat-Console.exe")
    if not os.path.exists(exe):
        print(f"[build] FAILED: expected exe not found: {exe}", file=sys.stderr)
        return 1

    # PyInstaller's EXE+COLLECT one-folder recipe also drops a broken stray
    # launcher at the dist root (no _internal beside it). Remove it so the only
    # usable artifact is the one-folder app under dist/Wordle-Strat-Console/.
    stray = os.path.join(DIST_DIR, "Wordle-Strat-Console.exe")
    if os.path.exists(stray):
        os.remove(stray)
        print(f"[build] removed stray root exe: {stray}")

    print(f"[build] OK -> {exe}")
    print("[build] note: this script does NOT launch the game.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
