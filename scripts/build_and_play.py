#!/usr/bin/env python3
"""One-shot: build (optional) + launch the GUI + replay the 47,814 live.

Convenience wrapper around the GUI replay harness. By default it just points
the harness at the dev server (instant — reuses committed source, no build).
Pass --build to first produce the frozen EXE via build_game.py, then replay
against that EXE instead (the true shipped artifact).

Run:
    python scripts/build_and_play.py                 # dev server, 2000 games, live window
    python scripts/build_and_play.py --all           # full 47,814 marathon
    python scripts/build_and_play.py --build --all   # build EXE, then full marathon on the EXE
    python scripts/build_and_play.py --limit 5000 --headless

The replay script lives at scripts/play_47814_gui.py (see its --help).
All artifacts stay in the workspace (report -> docs/gui_play_report.json).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build (optional) + live GUI replay.")
    ap.add_argument("--build", action="store_true",
                    help="build the frozen EXE first (via build_game.py)")
    ap.add_argument("--all", action="store_true", help="play all 47,814")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--headless", action="store_true")
    args, extra = ap.parse_known_args()

    exe = None
    if args.build:
        print("[bap] building EXE (build_game.py) ...")
        rc = subprocess.call([sys.executable, "build_game.py"], cwd=REPO_ROOT)
        if rc != 0:
            print("[bap] BUILD FAILED", file=sys.stderr)
            return rc
        exe = os.path.join(REPO_ROOT, "dist", "Wordle-Strat-Console",
                           "Wordle-Strat-Console.exe")
        if not os.path.exists(exe):
            print(f"[bap] exe missing: {exe}", file=sys.stderr)
            return 1
        print(f"[bap] built -> {exe}")

    cmd = [sys.executable, "scripts/play_47814_gui.py"]
    if exe:
        cmd += ["--target", "exe", "--exe", exe]
    if args.all:
        cmd.append("--all")
    else:
        cmd += ["--limit", str(args.limit)]
    if args.headless:
        cmd.append("--headless")
    # forward any other flags
    cmd += extra
    return subprocess.call(cmd, cwd=REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
