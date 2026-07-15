#!/usr/bin/env python3
"""Build the Wordle Strat-Console desktop app into a one-folder EXE.

Usage:
    python build_game.py            # clean build -> dist/Wordle-Strat-Console/
    python build_game.py --no-clean # keep PyInstaller's build/ work dir

This script ONLY builds. It never launches the game, so it cannot leave a
lingering process or spawn a fork-bomb. The frozen EXE runs its backend
in-process (desktop_app._is_frozen) and self-terminates on window close.

Determinism guarantee
---------------------
PyInstaller freezes *whatever is importable in the build environment*. If the
build is run inside a polluted venv (one carrying extra packages the app does
not use, e.g. boto3, lxml, openai), those extras get bundled too, making the
local artifact larger and NON-identical to the CI build (which installs only
`requirements.txt`). To prevent that, this script never uses the developer's
active venv. It creates a throwaway, clean build venv at `.venv_build/` and
installs exactly `requirements.txt` into it, then runs PyInstaller from there.
That is the same dependency boundary CI uses, so the locally built folder is
byte-comparable to the released artifact (modulo the unavoidable Python
patch-level skew between the local 3.12.x and CI's latest 3.12.x).
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

# Clean, CI-equivalent build venv. Git-ignored (see .gitignore: `.venv`).
BUILD_VENV = os.path.join(REPO_ROOT, ".venv_build")
BUILD_VENV_PY = os.path.join(BUILD_VENV, "Scripts", "python.exe")
REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")


def _clean_env() -> dict:
    """Return a copy of the environment with all pollution paths removed.

    The host machine has a global PYTHONPATH pointing at a generic agent
    venv (boto3, openai, lxml, ...) and a system-wide .pth that injects the
    same into every interpreter. If inherited, PyInstaller freezes those
    extras into the bundle and the local artifact becomes ~30 MB larger and
    NON-identical to the CI build (which installs only requirements.txt).
    Stripping PYTHONPATH (and disabling user-site) makes the clean build venv
    the sole source of imports, matching CI's dependency boundary.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    return env


def _rm(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)


def _resolve_base_python() -> str:
    """Find a 3.12+ interpreter to bootstrap the clean build venv.

    IMPORTANT: we must NOT seed from the project's own dev venv (.venv) — it
    is itself polluted with agent-environment packages (boto3, openai, lxml,
    ...) on this machine. To make the frozen bundle byte-comparable with CI,
    we bootstrap from an `uv`-provisioned CPython 3.12.13 (the exact patch CI
    pins). If uv is unavailable we fall back to the system Python 3.12. Either
    way we install ONLY requirements.txt and strip PYTHONPATH at build time.
    """
    target = "3.12.13"
    # Prefer a uv-managed interpreter so the local build freezes the SAME
    # CPython runtime patch as CI (eliminates the .pyd/.dll size skew). Run uv
    # with VIRTUAL_ENV unset so it searches managed/global installs rather
    # than being confused by any already-activated dev venv.
    uv_env = dict(os.environ)
    uv_env.pop("VIRTUAL_ENV", None)
    uv_py = subprocess.run(
        ["uv", "python", "find", target, "--no-project"],
        capture_output=True, text=True, env=uv_env,
    )
    if uv_py.returncode == 0 and uv_py.stdout.strip():
        cand = uv_py.stdout.strip().splitlines()[0].strip()
        if os.path.exists(cand):
            return cand
    sys_py = r"C:\Users\GIGABYTE\AppData\Local\Programs\Python\Python312\python.exe"
    for cand in (sys_py, "py -3.12", "python3.12", "python"):
        if os.path.exists(cand):
            return cand
    return "py -3.12"


def _ensure_build_venv() -> str:
    """Create a fresh `.venv_build` from requirements.txt; return its python.

    The build venv is a throwaway cache: we ALWAYS recreate it so a stale or
    previously-polluted venv can never leak extra packages (boto3, lxml, ...)
    into the frozen bundle. Recreation takes a few seconds and is the entire
    point of the clean-venv approach.
    """
    base = _resolve_base_python()
    print(f"[build] (re)creating clean build venv (.venv_build) from {base}")
    _rm(BUILD_VENV)
    # `base` may be "py -3.12"; split into argv for subprocess.
    base_argv = base.split()
    subprocess.run([*base_argv, "-m", "venv", BUILD_VENV], check=True)
    # Upgrade pip then install ONLY requirements.txt (CI-equivalent boundary).
    # Run with a sanitized env so the global PYTHONPATH / user-site pollution
    # on this host cannot be inherited into the venv.
    subprocess.run(
        [BUILD_VENV_PY, "-m", "pip", "install", "--upgrade", "pip"],
        check=True, env=_clean_env(),
    )
    subprocess.run(
        [BUILD_VENV_PY, "-m", "pip", "install", "-r", REQUIREMENTS],
        check=True, env=_clean_env(),
    )
    print("[build] clean build venv ready")
    return BUILD_VENV_PY


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

    py = _ensure_build_venv()

    # start from a clean output slot so a stale binary can never be reused
    _rm(DIST_DIR)
    _rm(STRAY_DIST)

    print(f"[build] PyInstaller spec : {SPEC}")
    print(f"[build] build python     : {py}")
    print(f"[build] output           : {DIST_DIR}/Wordle-Strat-Console/")
    cmd = [
        py, "-m", "PyInstaller",
        SPEC,
        "--noconfirm",
        "--clean",
        f"--distpath={DIST_DIR}",
    ]
    print("[build] running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=REPO_ROOT, env=_clean_env())
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
