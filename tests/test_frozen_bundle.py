"""Self-play verification of the FROZEN one-folder bundle.

Why this exists: the other tests exercise source code, but a frozen PyInstaller
bundle can still break (missing datas, a bad resource_path, a nohint-tree artifact
that didn't get bundled). This test launches the actual built exe from its folder
and drives its HTTP API through hard no-hint self-play on every residual word,
proving the shipped artifact closes — not just the source.

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
    # Build if absent so the suite is self-sufficient.
    if not os.path.exists(EXE):
        subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "build_dist.py")], check=True
        )
    assert os.path.exists(EXE), "frozen bundle missing even after build"

    port = _find_free_port()
    env = dict(os.environ, WSC_PORT=str(port))
    proc = subprocess.Popen([EXE], cwd=FOLDER, env=env)
    try:
        if not _wait_for_server(port):
            pytest.fail("frozen bundle did not come up on its HTTP API")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


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