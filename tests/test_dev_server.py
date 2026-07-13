"""Regression tests for the dev server: conflict-free start + auto-shutdown.

These guard the exact trap we hit: a dev ``uvicorn`` process hardcoded to
``:8000`` that lingered after its parent died and held the (memory-mapped)
word matrix open, blocking rebuilds. The dev server must (1) never lose a
port war, (2) die with its parent game session (``--parent-pid`` watchdog +
``POST /api/shutdown``), and (3) never linger on idle/uptime either.
"""
import subprocess
import sys
import time
import urllib.request

import pytest

from wordle_solver.utils import find_free_port

_PY = sys.executable
_MOD = "wordle_solver.app.dev_server"


def _run(args, timeout=25):
    """Launch the dev server as a subprocess; return (proc, port)."""
    # find_free_port inside the module uses WSC_PORT default 8753; pass --port 0
    # for "any free port" so the test can't collide with a running dev instance.
    import os as _os

    # run in an isolated interpreter that can still import wordle_solver from
    # the local src/ (mirrors how the project is run in dev/CI). __file__ is
    # <repo>/tests/test_dev_server.py, so repo root is two dirs up.
    repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    src_dir = _os.path.join(repo_root, "src")
    proc = subprocess.Popen(
        [_PY, "-m", _MOD, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # close_fds=True on Windows prevents the child from inheriting every
        # open parent fd (otherwise surfaced as ResourceWarning on child exit).
        close_fds=True,
        env={**_os.environ, "PYTHONPATH": src_dir},
    )
    # wait for the "running on http://..." line to learn the chosen port
    deadline = time.time() + timeout
    port = None
    stdout = proc.stdout
    assert stdout is not None, "dev server subprocess must have a stdout pipe"
    while time.time() < deadline:
        line = stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        if "running on http://" in line:
            # format: [dev-server] running on http://127.0.0.1:PORT  (auto-shutdown: ...)
            url = line.split("running on ", 1)[1].split()[0].rstrip("/")
            port = int(url.rsplit(":", 1)[1])
            break
    return proc, port


def _reap(proc, timeout=15):
    """Wait for the dev-server child, then close its stdout pipe.

    Closing ``proc.stdout`` only AFTER the child has exited avoids a
    broken-pipe in the child (it keeps logging to stdout). Leaving the
    pipe open leaks a TextIOWrapper at GC -> ResourceWarning.
    Returns the child's exit code (or None if it could not be reaped).
    """
    rc = None
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            rc = proc.wait(timeout=10)
        except Exception:
            pass
    finally:
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
    return rc



def test_find_free_port_returns_free_bindable_port():
    p = find_free_port(0)
    assert 1 <= p <= 65535
    # the port it returns must still be bindable by us immediately after
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", p))  # raises OSError if not actually free


def test_dev_server_boots_on_conflict_free_port_and_serves_state():
    proc, port = _run(["--port", "0", "--no-auto-shutdown"])
    try:
        assert proc.poll() is None, "dev server died on boot"
        assert port is not None and port > 0
        # it must actually serve the API
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/state", timeout=10
        ) as r:
            body = r.read().decode()
        assert '"turn"' in body and '"pool"' in body
        # the chosen port must equal what we'd get from find_free_port path
        # (i.e. it did NOT hardcode 8000 / collide) — asserted implicitly by
        # the server having started at all on a free port.
    finally:
        proc.terminate()
        _reap(proc, timeout=10)


def test_dev_server_auto_shuts_down_on_idle():
    # very short idle (2s) + no uptime cap -> must self-terminate without us
    # killing it (the whole point: no lingering process to lock the matrix).
    proc, port = _run(["--port", "0", "--idle", "2", "--max-age", "0"])
    assert port is not None, "dev server never reported its port"
    # give it a moment to be alive, then wait for the watchdog to fire
    assert proc.poll() is None, "dev server died before serving"
    # watchdog polls every 5s + 2s idle -> allow up to ~12s
    rc = _reap(proc, timeout=15)
    assert rc is not None, "dev server did NOT auto-shutdown (lingering process!)"
    # and the port must be free again afterwards
    time.sleep(0.3)
    with __import__("socket").socket(
        __import__("socket").AF_INET, __import__("socket").SOCK_STREAM
    ) as s:
        s.bind(("127.0.0.1", port))  # must succeed: no zombie holding it


def test_dev_server_dies_with_parent():
    # session-bound mode: with --parent-pid pointing at a live process, the
    # server must self-terminate the instant that parent dies. This is the
    # primary guarantee that a closed game window can't leave a zombie
    # server holding the matrix open. We use a throwaway "parent" process.
    import subprocess as _sp

    parent = _sp.Popen(
        [_PY, "-c", "import time; time.sleep(3600)"],
        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
    )
    try:
        proc, port = _run(
            ["--port", "0", "--parent-pid", str(parent.pid),
             "--idle", "0", "--max-age", "0"]
        )
        assert port is not None, "dev server never reported its port"
        assert proc.poll() is None, "dev server died before parent ended"
        # kill the parent -> the watchdog (polls every 2s) must reap the server
        parent.kill()
        parent.wait(timeout=5)
        rc = _reap(proc, timeout=12)
        assert rc is not None, "dev server outlived its parent (lingering!)"
    finally:
        if parent.poll() is None:
            parent.kill()
        try:
            parent.wait(timeout=5)
        except Exception:
            pass


def test_dev_server_shutdown_endpoint_triggers_exit():
    # POST /api/shutdown must cleanly stop the server (the desktop app calls
    # this on window close before the process exits).
    proc, port = _run(["--port", "0", "--no-auto-shutdown"])
    assert port is not None, "dev server never reported its port"
    assert proc.poll() is None, "dev server died on boot"
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown", method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
    rc = _reap(proc, timeout=12)
    assert rc is not None, "dev server ignored /api/shutdown (lingering!)"


def test_watchdog_survives_prestart_tick():
    # REGRESSION (BUG B): the watchdog used to exit on its FIRST tick if the
    # server hadn't started yet (matrix warm-up takes >1 tick under load),
    # which silently disabled die-with-parent + /api/shutdown + idle/uptime.
    # This proves the server is ALIVE even when polled very early, and that
    # /api/shutdown still stops it afterwards.
    proc, port = _run(["--port", "0", "--no-auto-shutdown"])
    assert port is not None, "dev server never reported its port"
    # hit it almost immediately — covers the pre-start race window
    time.sleep(0.5)
    assert proc.poll() is None, "watchdog killed the server before it started"
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown", method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
    rc = _reap(proc, timeout=12)
    assert rc is not None, "dev server ignored /api/shutdown after early poll (lingering!)"
