"""Self-play verification of the FROZEN one-folder bundle.

Why this exists: the other tests exercise source code, but a frozen PyInstaller
bundle can still break (missing datas, a bad resource_path, a specialist-tree
artifact that didn't get bundled). This test launches the actual built exe from
its folder and drives its HTTP API through self-play — hard no-hint on every
residual word AND hinted (1-hint / 2-hint) games — proving the shipped artifact
closes, and that it actually carries the hint specialist trees, not just the
source.

It builds the bundle via build_dist.py if it isn't present, so it's self-sufficient.
The app serves HTTP on a runtime-chosen port; we pin it with WSC_PORT to a free port
and poll that. The native window is allowed to open (headless hosts without WebView2
would fail to boot — that's a real signal, not a test bug).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ROOT)  # parent of tests/
NAME = "Wordle-Strat-Console"
FOLDER = os.path.join(REPO_ROOT, "dist", NAME)
EXE = os.path.join(FOLDER, NAME + ".exe")

# The six words the exhaustive gate must still close in hard no-hint.
RESIDUALS = ["foyer", "hound", "mound", "hatch", "hunch", "latch"]


def _find_free_port(preferred: int = 8899, attempts: int = 20) -> int:
    for off in range(attempts):
        p = preferred + off
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free localhost port for frozen-bundle test")


def _api(port: int, path: str, payload=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET"
    )
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _states_from_pattern(pat):
    """Engine.calculate_pattern returns the int pattern (sum state*3**i); the
    HTTP API wants the 5-element list of states {0,1,2}."""
    if isinstance(pat, int):
        return [(pat // (3 ** i)) % 3 for i in range(5)]
    return list(pat)


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1.0)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _play(port, engine, secret) -> int | None:
    """Self-play `secret` in hard no-hint by following the solver's top guess.
    Returns the winning turn (1..6) or None if it failed."""
    _api(port, "/api/reset", {})
    _api(port, "/api/hard", {"on": True})
    for turn in range(1, 7):
        st = _api(port, "/api/state")
        if st.get("solved"):
            return st.get("turn", turn)
        # The state route already carries the ranked suggestions.
        guess = st["strat"][0]["word"]
        colors = _states_from_pattern(engine.calculate_pattern(guess, secret))
        res = _api(port, "/api/submit", {"guess": guess, "colors": colors})
        if res.get("solved"):
            # The engine reports turn 7 after the 6th submit; the human-visible
            # move number is the count of submits we just made.
            return turn if 1 <= turn <= 6 else 6
    return None


_VOWELS = set("aeiou")


def _play_hinted(port, engine, secret, hint_letters) -> int | None:
    """Self-play `secret` after logging `hint_letters` (drawn from the secret)
    before turn 1, so the shipped bundle exercises the 1-hint / 2-hint
    specialist trees — the artifacts that must be bundled for hinted play to
    close. Returns the winning turn (1..6) or None on failure."""
    _api(port, "/api/reset", {})
    for h in hint_letters:
        _api(port, "/api/hint", {"letter": h})
    for turn in range(1, 7):
        st = _api(port, "/api/state")
        if st.get("solved"):
            return st.get("turn", turn)
        guess = st["strat"][0]["word"]
        colors = _states_from_pattern(engine.calculate_pattern(guess, secret))
        res = _api(port, "/api/submit", {"guess": guess, "colors": colors})
        if res.get("solved"):
            return turn if 1 <= turn <= 6 else 6
    return None


# The frozen-bundle test stands up the actual built EXE — a heavy,
# environment-fragile PyInstaller build (and the EXE opens a native window
# on a real desktop). It is therefore opt-in via WS_BUILD_TEST=1 (a dedicated
# CI build job runs it), keeping the default `pytest` run fast and green and
# avoiding a window pop on every dev loop. When opted in it builds the bundle
# if absent and self-plays the hard no-hint residuals through the shipped
# artifact's HTTP API — it is NOT skipped, merely isolated.
_BUILD_OPT_IN = os.environ.get("WS_BUILD_TEST") == "1"


@pytest.fixture(scope="module")
def running_exe():
    # Build if absent (or a stale/zero-byte artifact was left behind) so the
    # suite is self-sufficient and never launches a non-executable placeholder.
    if not os.path.exists(EXE) or os.path.getsize(EXE) < 1_000_000:
        subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "build_dist.py")], check=True
        )
    assert os.path.exists(EXE) and os.path.getsize(EXE) >= 1_000_000, "frozen bundle missing/invalid even after build"

    port = _find_free_port()
    env = dict(os.environ, WSC_PORT=str(port))
    proc = subprocess.Popen([EXE], cwd=FOLDER, env=env)
    try:
        if not _wait_for_server(port):
            pytest.fail("frozen bundle did not come up on its HTTP API")
        yield port
    finally:
        # In a headless CI host the native window may never open, so the frozen
        # EXE won't exit on terminate() (no window to close -> WebView2 keeps it
        # alive). Use taskkill /F (what a real user's window-close triggers via
        # the app's own teardown) so the test never hangs. Wait briefly for the
        # kill to land so the Popen object is reaped (avoids an unraisable
        # ResourceWarning under -W error).
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
            )
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@pytest.fixture(scope="module")
def running_exe_default_port():
    # Build if absent so the suite is self-sufficient.
    if not os.path.exists(EXE):
        subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "build_dist.py")], check=True
        )
    assert os.path.exists(EXE), "frozen bundle missing even after build"

    # DEFAULT launch path: NO WSC_PORT env override. This is exactly the path
    # that regressed (boot() re-probed a port the server already held, so the
    # window waited on an empty port). The bundle must come up on whatever free
    # port it auto-chooses and serve its HTTP API without any env hint.
    env = {k: v for k, v in os.environ.items() if k != "WSC_PORT"}
    proc = subprocess.Popen([EXE], cwd=FOLDER, env=env)
    try:
        # Discover the auto-chosen port by scanning the listeners this exe owns.
        import subprocess as _sp
        listing = _sp.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
             "Where-Object { $_.OwningProcess -in "
             "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'Wordle-Strat-Console.exe' } "
             "| Select-Object -ExpandProperty ProcessId) } | Select-Object -ExpandProperty LocalPort"],
            capture_output=True, text=True,
        ).stdout.split()
        # Tight candidate set: prefer the shell probe; otherwise only sweep a
        # small window around the preferred port so CI can never hang on a
        # slow 600-port fallback.
        found = [int(p) for p in listing if p.strip().isdigit()]
        candidates = found if found else [8753 + i for i in range(30)]
        up = None
        for p in candidates:
            if _wait_for_server(p, timeout=2.0):
                up = p
                break
        if up is None:
            pytest.fail("frozen bundle (default port) did not come up on its HTTP API")
        yield up
    finally:
        # In a headless CI host the native window may never open, so the frozen
        # EXE won't exit on terminate() (no window to close -> WebView2 keeps it
        # alive). Use taskkill /F (what a real user's window-close triggers via
        # the app's own teardown) so the test never hangs. Wait briefly for the
        # kill to land so the Popen object is reaped (avoids an unraisable
        # ResourceWarning under -W error).
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
            )
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@pytest.mark.skipif(not _BUILD_OPT_IN,
                    reason="set WS_BUILD_TEST=1 to run the heavy frozen-bundle build test")
def test_frozen_bundle_default_port_comes_up(running_exe_default_port):
    # The default (no WSC_PORT) launch must serve the solver without an env hint.
    st = _api(running_exe_default_port, "/api/state")
    assert st.get("turn") == 1, "default-port bundle served an unexpected state"


@pytest.mark.skipif(not _BUILD_OPT_IN,
                    reason="set WS_BUILD_TEST=1 to run the heavy frozen-bundle build test")
def test_frozen_bundle_solves_all_residuals(running_exe):
    from wordle_solver.engine import WordleEngine

    e = WordleEngine()
    for secret in RESIDUALS:
        turn = _play(running_exe, e, secret)
        assert turn is not None and 1 <= turn <= 6, (
            f"frozen bundle failed to close residual '{secret}' "
            f"(turn={turn}) within 6 moves"
        )


@pytest.mark.skipif(not _BUILD_OPT_IN,
                    reason="set WS_BUILD_TEST=1 to run the heavy frozen-bundle build test")
def test_frozen_bundle_solves_all_30_residuals(running_exe):
    """Self-play all 30 'proven-residual' seed words (the 628 games stamped in
    EXHAUSTIVE_ENUMERATION.txt) through the SHIPPED exe in normal_0 and hard_0.
    The report marks those games from the gate cache; this replays them LIVE
    through the frozen artifact so the bundled specialist trees are proven
    present and solving. Duplicates the logic of scripts/prove_residuals_exe.py
    so the proof is part of `pytest`, not just a standalone script."""
    from wordle_solver.engine import WordleEngine

    e = WordleEngine()
    SEEDS = [
        "baste", "bitty", "boxer", "chard", "cower", "dilly", "ditty", "foyer",
        "glade", "golly", "goner", "graze", "hatch", "homer", "hound", "hunch",
        "latch", "mound", "shale", "shave", "sight", "sower", "stash", "taffy",
        "tight", "valor", "vaunt", "width", "wight", "wound",
    ]
    for secret in SEEDS:
        for hard in (False, True):
            _api(running_exe, "/api/reset", {})
            _api(running_exe, "/api/hard", {"on": hard})
            solved = False
            for _ in range(1, 7):
                st = _api(running_exe, "/api/state")
                if st.get("solved"):
                    solved = True
                    break
                guess = st["strat"][0]["word"]
                pat = e.calculate_pattern(guess, secret)
                colors = [(pat // (3 ** i)) % 3 for i in range(5)]
                res = _api(running_exe, "/api/submit",
                           {"guess": guess, "colors": colors})
                if res.get("solved"):
                    solved = True
                    break
            assert solved, (
                f"exe failed to close residual '{secret}' (hard={hard}) within 6"
            )
    """Self-play hinted games through the SHIPPED exe so the bundle proves it
    carries the 1-hint AND 2-hint specialist trees. Before these artifacts were
    added to the spec's datas, the loaders silently fell back to {} in the
    frozen bundle — invisible to the no-hint self-play above. Each secret is
    played with a hint set drawn from its own letters (NYT rule: <=1 vowel and
    <=1 consonant)."""
    from wordle_solver.engine import WordleEngine

    e = WordleEngine()
    # (secret, hint letters) — a 2-hint (vowel+consonant) and a 1-hint case.
    cases = [
        ("hatch", ["a", "h"]),   # 2-hint: vowel 'a' + consonant 'h'
        ("foyer", ["o"]),        # 1-hint: single vowel
        ("mound", ["m"]),        # 1-hint: single consonant
    ]
    for secret, hints in cases:
        turn = _play_hinted(running_exe, e, secret, hints)
        assert turn is not None and 1 <= turn <= 6, (
            f"frozen bundle failed to close hinted '{secret}' "
            f"(hints={hints}, turn={turn}) within 6 moves — is the "
            f"1-hint/2-hint tree bundled?"
        )