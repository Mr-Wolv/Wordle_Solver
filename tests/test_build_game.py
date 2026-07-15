"""Regression tests for build_game.py (the EXE build entrypoint).

These lock the contract: the script builds via the spec, never launches the
game (so it can't spawn a lingering process or fork-bomb), and fails cleanly
when the spec is missing. We exercise the logic without running a full
PyInstaller build (that's covered by test_frozen_bundle / the real build run).
"""
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module():
    path = os.path.join(REPO_ROOT, "build_game.py")
    spec = importlib.util.spec_from_file_location("build_game", path)
    assert spec is not None and spec.loader is not None, "build_game.py spec unloadable"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_script_imports_and_has_expected_constants():
    mod = _load_module()
    assert os.path.isabs(mod.REPO_ROOT)
    assert os.path.exists(mod.SPEC), "spec referenced by build_game.py must exist"
    assert mod.DIST_DIR.endswith("dist")
    # the one safety guarantee: building must never launch the game
    with open(os.path.join(REPO_ROOT, "build_game.py")) as fh:
        src = fh.read()
    assert "does NOT launch" in src


def test_main_fails_cleanly_when_spec_missing(monkeypatch):
    mod = _load_module()
    # argparse reads sys.argv; isolate it from the pytest invocation args
    monkeypatch.setattr(sys, "argv", ["build_game.py"])
    # point SPEC at a nonexistent file and stub subprocess so no build runs
    monkeypatch.setattr(mod, "SPEC", os.path.join(REPO_ROOT, "nope.spec"))
    called = {}

    def _fake_call(cmd, cwd=None, **_kwargs):
        called["cmd"] = cmd
        return 1  # should never be reached

    monkeypatch.setattr(mod.subprocess, "call", _fake_call)
    rc = mod.main()
    assert rc == 1
    assert "cmd" not in called, "subprocess must not run when spec is missing"


def test_help_flag_exits_zero():
    mod = _load_module()
    # argparse --help exits 0 and documents the --no-clean flag
    import subprocess

    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "build_game.py"), "--help"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "--no-clean" in proc.stdout


def test_no_stray_root_exe_after_build(tmp_path, monkeypatch):
    """The one-folder EXE+COLLECT recipe leaves a broken stray launcher at the
    dist root; build_game.py must delete it so only the one-folder app remains.
    We simulate a prior stray and assert the cleanup path runs."""
    mod = _load_module()
    monkeypatch.setattr(sys, "argv", ["build_game.py"])
    # prevent main() from wiping DIST_DIR so our simulated build output survives
    monkeypatch.setattr(mod, "_rm", lambda _p: None)
    # don't actually provision a build venv (slow / env-specific); the PyInstaller
    # call is mocked below, so main() only needs *a* python path.
    monkeypatch.setattr(mod, "_ensure_build_venv", lambda: sys.executable)
    # fake a stray root exe + the real one-folder exe (as if pyinstaller wrote them)
    stray = os.path.join(REPO_ROOT, "dist", "Wordle-Strat-Console.exe")
    real_dir = os.path.join(REPO_ROOT, "dist", "Wordle-Strat-Console")
    real_exe = os.path.join(real_dir, "Wordle-Strat-Console.exe")
    os.makedirs(real_dir, exist_ok=True)
    with open(stray, "w"):
        pass
    with open(real_exe, "w"):
        pass

    def _fake_call(cmd, cwd=None, **_kwargs):
        return 0  # pretend pyinstaller succeeded

    monkeypatch.setattr(mod.subprocess, "call", _fake_call)
    rc = mod.main()
    assert rc == 0
    assert not os.path.exists(stray), "stray root exe must be removed"
    assert os.path.exists(real_exe), "real one-folder exe must be preserved"
    # tidy the simulated artifacts so we don't leave junk in the real dist/
    import shutil as _sh

    _sh.rmtree(real_dir, ignore_errors=True)
