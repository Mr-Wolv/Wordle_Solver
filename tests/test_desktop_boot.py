"""Regression tests for the desktop backend lifecycle.

These lock the contract you asked for: in a *source/dev* run the desktop app
must launch the backend as a **session-bound dev-server child** (not run it
in-process), passing ``--parent-pid`` so the server dies with the window and
can never linger holding the matrix open. The frozen bundle legitimately runs
in-process (a subprocess can't import the packaged code) and is covered by the
frozen-bundle test.
"""
import os
import sys
import subprocess as _sp

import pytest

import wordle_solver.desktop.desktop_app as desktop


def _fake_window(port_holder: list):
    """Minimal stand-in for a pywebview window."""

    class _Win:
        def evaluate_js(self, js):
            # capture the __setPort call so we know which port boot chose
            if "__setPort" in js:
                port_holder.append(int(js.split("(")[1].rstrip(");")))

        def load_url(self, url):
            port_holder.append(url)

    return _Win()


def test_boot_spawns_dev_server_child_with_parent_pid(monkeypatch):
    # Capture the child command instead of really launching a server.
    launched = {}

    class _FakeProc:
        def __init__(self, cmd):
            launched["cmd"] = cmd
            self._port = None
            self.returncode = None

        def poll(self):
            return None  # pretend it's still alive

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    def _fake_popen(cmd, *a, **k):
        return _FakeProc(cmd)

    monkeypatch.setattr(_sp, "Popen", _fake_popen)
    # desktop boot() calls _wait_for_server; make it think the server is up
    monkeypatch.setattr(desktop, "_wait_for_server", lambda port: True)

    ports = []
    win = _fake_window(ports)
    ok = desktop.boot(win)

    assert ok is True
    cmd = launched["cmd"]
    # it must launch the dev server module, bound to this process as parent
    assert "wordle_solver.app.dev_server" in cmd, cmd
    assert "--parent-pid" in cmd, cmd
    assert str(os.getpid()) in cmd, cmd
    # and it must have recorded the child so close paths can stop it
    assert desktop._DEV_SERVER_PROC is not None
    # not in-process (no uvicorn thread path taken in source mode)
    assert desktop._is_frozen() is False


def test_stop_dev_server_posts_shutdown(monkeypatch):
    # _stop_dev_server must hit /api/shutdown on the recorded child port.
    seen = {}

    class _FakeProc:
        def __init__(self, port):
            self._port = port
            self.returncode = None

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    import urllib.request

    real_urlopen = urllib.request.urlopen

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url if hasattr(req, "full_url") else str(req)
        return real_urlopen.__class__  # not used; we just need the side effect

    # build a minimal Request-like so we capture the URL
    class _Req:
        full_url = None

    def _fake_urlopen2(target, timeout=None):
        seen["url"] = target
        return _Req()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen2)
    desktop._DEV_SERVER_PROC = _FakeProc(8731)
    desktop._stop_dev_server()
    assert seen.get("url") == "http://127.0.0.1:8731/api/shutdown"
    assert desktop._DEV_SERVER_PROC is None


def test_boot_reaps_child_on_failed_start(monkeypatch):
    # REGRESSION (BUG A): a dev-server child that fails to come up must be
    # killed by boot() — otherwise each failed retry leaves an orphan holding
    # the matrix mmap open (the exact defect that locked rebuilds).
    spawned = []
    killed = []

    class _FakeProc:
        def __init__(self, cmd):
            self._cmd = cmd
            self._port = None
            self.returncode = None
            spawned.append(self)

        def poll(self):
            return None  # pretend it never exits on its own

        def kill(self):
            killed.append(self)  # boot must call this on failure

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(_sp, "Popen", lambda cmd, *a, **k: _FakeProc(cmd))
    # make the server never accept connections -> every attempt fails
    monkeypatch.setattr(desktop, "_wait_for_server", lambda port: False)
    # neutralize the per-attempt sleep so the test is fast
    class _FastTime:
        @staticmethod
        def sleep(s):
            return None

    monkeypatch.setattr(desktop, "time", _FastTime)
    # boot() calls show_fatal() on exhaustion, which opens a blocking
    # MessageBoxW in a real run — stub it so the test stays headless.
    monkeypatch.setattr(desktop, "show_fatal", lambda *a, **k: None)

    win = _fake_window([])
    ok = desktop.boot(win)

    assert ok is False  # exhausted retries
    assert spawned, "boot spawned no children at all?"
    assert len(killed) == len(spawned), (
        f"leaked {len(spawned) - len(killed)} dev-server child(ren): "
        f"{len(spawned)} spawned, {len(killed)} killed"
    )
    assert desktop._DEV_SERVER_PROC is None
