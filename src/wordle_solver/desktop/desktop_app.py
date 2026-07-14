"""Wordle Strat-Console — desktop wrapper.

Opens the DOM frontend (``web/``) inside a native **pywebview** window and
runs the FastAPI backend as a *child* ``dev_server`` process (not in-process).
The child is launched with ``--parent-pid`` so it self-terminates the instant
this game session ends — a closed window can never leave a zombie server
holding the (memory-mapped) matrix file open.

Runtime robustness (the point of this rewrite):
  * PORT is picked at runtime from a free socket (env WSC_PORT overrides the
    preferred base). No more "port 8753 already in use" dead ends.
  * The backend child is started with RETRY across several candidate ports; a
    transient bind clash is absorbed automatically.
  * If the app can't come up (or crashes mid-run), the user sees a clear,
    non-technical error card — what happened, why, and how to fix it — with
    the raw detail available and a Retry button. Nothing fails silently to a
    black screen (the console is hidden in the one-file exe, so we surface
    problems in-window instead).
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

def file_uri(path: str) -> str:
    """Correct file:// URI for WebView2 (needs 3 slashes + forward slashes).

    On Windows ``file://C:\\foo`` is rejected and shows "file not found";
    ``Path(...).as_uri()`` yields the valid ``file:///C:/foo``.
    """
    return Path(path).resolve().as_uri()
import webview  # light import — window layer only; backend imported lazily
from webview.window import Window
from wordle_solver.utils import assets_path, find_free_port

PREFERRED_PORT = int(os.environ.get("WSC_PORT", "8753"))
MAX_ATTEMPTS = 6  # how many consecutive ports to try before giving up
POLL_TIMEOUT = 20.0  # generous: first /api/state triggers the lazy matrix load

APP_WINDOW = None  # set after window creation; used by the crash handler


def _wait_for_server(port: int, timeout: float = POLL_TIMEOUT) -> bool:
    url = f"http://127.0.0.1:{port}/api/state"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1.0)
            return True
        except Exception:
            time.sleep(0.15)
    return False


# ── crash reporting ──────────────────────────────────────────────────────────
def show_fatal(title: str, reason: str, fixes: list[str], detail) -> None:
    """Surface a failure to the user in plain language.

    If a window exists we render a styled card (with a Retry button for the
    backend-start path); otherwise we fall back to a Windows MessageBox so a
    pre-window crash is still explained. The process is left alive so the
    message can be read; closing the window exits.
    """
    fixes_html = "".join(f"<li>{_esc(f)}</li>" for f in fixes)
    detail_text = _esc("".join(traceback.format_exception(type(detail), detail, getattr(detail, "__traceback__", None))) if detail else "—")
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="device-width,initial-scale=1">
<style>
:root{{--bg:#0b0e14;--panel:#161d2b;--red:#ff5d5d;--subtle:#9aa7bd;--faint:#6b788f}}
*{{box-sizing:border-box}}
html,body{{margin:0;height:100%;background:var(--bg);color:#eef2f8;
font-family:"Segoe UI",system-ui,sans-serif;overflow:auto}}
.wrap{{min-height:100%;display:flex;align-items:center;justify-content:center;padding:32px}}
.card{{max-width:680px;width:100%;background:var(--panel);border:1px solid #2a3344;
border-radius:14px;padding:28px 30px;box-shadow:0 12px 40px rgba(0,0,0,.45)}}
.x{{font-size:34px;color:var(--red);line-height:1}}
h1{{margin:0 0 6px;font-size:20px;letter-spacing:.3px}}
.reason{{color:var(--subtle);font-size:14px;margin:10px 0 16px;line-height:1.5}}
ul{{margin:0 0 16px;padding-left:20px;color:var(--subtle);font-size:13px;line-height:1.7}}
ul b{{color:#eef2f8}}
pre{{background:#0c111b;border:1px solid #232c3c;border-radius:8px;padding:12px;
color:#8fa0bb;font-size:11px;max-height:200px;overflow:auto;white-space:pre-wrap;word-break:break-word}}
button{{margin-top:6px;background:var(--red);color:#1a0d0d;border:0;border-radius:8px;
padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer}}
button:active{{transform:translateY(1px)}}
.muted{{color:var(--faint);font-size:11px;margin-top:14px}}
</style></head><body><div class="wrap"><div class="card">
<div class="x">⚠</div>
<h1>{_esc(title)}</h1>
<div class="reason">{_esc(reason)}</div>
<p style="margin:0 0 6px;font-size:13px;color:#eef2f8"><b>How to fix it</b></p>
<ul>{fixes_html}</ul>
<p style="margin:0 0 4px;font-size:12px;color:var(--faint)">Technical detail</p>
<pre>{detail_text}</pre>
<button onclick="retry()">Retry</button>
<div class="muted">If Retry doesn't help, copy the detail above when reporting the issue.</div>
</div></div>
<script>
function retry(){{
  if (window.pywebview && window.pywebview.api && window.pywebview.api.retry) {{
    window.pywebview.api.retry();
  }} else {{
    alert("Retry not available yet — please restart the app.");
  }}
}}
</script></body></html>"""
    path = tempfile.mktemp(suffix=".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    if APP_WINDOW is not None:
        try:
            APP_WINDOW.load_url(file_uri(path))
            return
        except Exception:
            pass
    # No window yet (pre-startup crash): Windows MessageBox fallback.
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{reason}\n\n" + "\n".join(fixes) + f"\n\n{detail_text[:600]}",
            title,
            0x10,  # MB_ICONERROR
        )


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _crash_hook(et, ev, tb):
    show_fatal(
        "Unexpected error",
        "The app hit an unexpected error and stopped.",
        [
            "Close this window and relaunch the app.",
            "If it repeats, the technical detail below is what to report.",
        ],
        ev,
    )


sys.excepthook = _crash_hook


# ── backend boot ────────────────────────────────────────────────────────────
# SOURCE / dev runs: the backend runs as a *child* ``dev_server`` process. This
# is deliberate — it is the single server implementation, and it self-terminates
# when this parent process dies (--parent-pid watchdog) or on /api/shutdown, so
# a closed window can never leave a zombie server holding the matrix open.
# FROZEN bundle: a subprocess can't import the packaged modules (sys.executable
# is the EXE), so we run the server in-process. CRITICAL: in the frozen bundle
# the server is started in ``start_frozen_server`` *before* ``webview.start`` so
# the backend is ALWAYS reachable — even on a headless host or when WebView2
# cannot open a native window — rather than only after the window comes up. This
# also means a broken WebView2 can no longer silently take the whole backend
# down (the old bug: boot() was called from inside webview.start, so a window
# failure left the port unbound and the bundle unverifiable). Either way the
# server's life is bound to the game session — it runs on a daemon thread and
# the whole process (and its memory-mapped matrix) is torn down on window close.
_DEV_SERVER_PROC = None  # module-level handle so close paths can stop it
_FROZEN_SERVER_PORT: int | None = None  # port the frozen bundle's server bound


def _is_frozen() -> bool:
    return bool(
        getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
    )


def start_frozen_server(port: int) -> None:
    """Frozen bundle: start the in-process HTTP backend on ``port``.

    Called from ``main()`` *before* ``webview.start`` so the solver is live
    and verifiable even when no native window can be created (headless CI /
    a host without WebView2). The server runs on a daemon thread; the process
    — and therefore the server and its memory-mapped matrix — is released on
    window close. The splash already points at ``port`` (it is included in the
    splash URL as ``#port=...``), so the frontend connects immediately.
    """
    import uvicorn
    import wordle_solver.app.web_server as web_server

    web_server.configure_engine(port)
    web_server.set_load_status("Loading word matrix…")
    try:
        web_server.engine.get_suggestions()
        web_server.engine.get_suggestions(is_hard_mode=True)
    except Exception:
        pass
    web_server.set_load_status("Ready")
    srv = uvicorn.Server(
        uvicorn.Config(web_server.app, host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=srv.run, daemon=True).start()
    global _FROZEN_SERVER_PORT
    _FROZEN_SERVER_PORT = port


def _stop_dev_server() -> None:
    """Ask the backend child to exit cleanly, then hard-kill if needed."""
    global _DEV_SERVER_PROC
    proc = _DEV_SERVER_PROC
    if proc is None:
        return
    _DEV_SERVER_PROC = None
    try:
        import urllib.request

        # best-effort clean shutdown via the dev server's own endpoint
        urllib.request.urlopen(
            f"http://127.0.0.1:{getattr(proc, '_port', 0)}/api/shutdown",
            timeout=1.0,
        )
    except Exception:
        pass
    # give uvicorn a beat to drain, then ensure it's gone
    for _ in range(20):
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        proc.kill()
    except Exception:
        pass


def boot(window) -> bool:
    """Start the backend and point the window at it.

    In source/dev, the backend is a *session-bound* dev-server child. In a
    frozen bundle it runs in-process (a subprocess can't import the packaged
    code). Returns True on success or False after exhausting port retries.

    Every child spawned by a failed attempt is reaped immediately, so a retry
    can never leave an orphaned server holding the matrix open — the exact
    trap that used to lock rebuilds.

    Args:
        window: the pywebview window to load the app into.
    """
    my_pid = os.getpid()
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        proc = None          # in-flight dev-server child (source mode)
        try:
            port = find_free_port(PREFERRED_PORT + attempt - 1)
            try:
                window.evaluate_js(f"if(window.__setPort)window.__setPort({port});")
            except Exception:
                pass

            if _is_frozen():
                # Frozen bundle: the server was already started in
                # ``start_frozen_server`` (called from main() *before*
                # webview.start) on ``_FROZEN_SERVER_PORT`` — use THAT exact
                # port. Re-deriving it via find_free_port here would skip the
                # port our own server is bound to (the probe can't re-bind it)
                # and wait on the wrong, empty port -> "never came up". The
                # server is reachable even without a window, so just verify
                # and point the window at it.
                port = _FROZEN_SERVER_PORT
                if port is None:
                    # Defensive: shouldn't happen (main sets it before boot),
                    # but fall back to a fresh probe rather than failing blind.
                    port = find_free_port(PREFERRED_PORT + attempt - 1)
                if _wait_for_server(port):
                    window.load_url(f"http://127.0.0.1:{port}/")
                    return True
                show_fatal(
                    "Backend failed to start",
                    "The solver engine couldn't be reached after launch.",
                    [
                        "Relaunch the app — the backend should start automatically.",
                    ],
                    RuntimeError(f"frozen server on :{port} never came up"),
                )
                return False
            else:
                # Source/dev: spawn the shared dev server as a child; it warms
                # its own cache and self-terminates when this process ends.
                import subprocess

                proc = subprocess.Popen(
                    [
                        sys.executable, "-m", "wordle_solver.app.dev_server",
                        "--port", str(port), "--parent-pid", str(my_pid),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                proc._port = port

            if _wait_for_server(port):
                global _DEV_SERVER_PROC
                _DEV_SERVER_PROC = proc  # None in frozen mode (in-process)
                window.load_url(f"http://127.0.0.1:{port}/")
                return True
            # didn't come up — reap THIS attempt's child so it can't linger
            if proc is not None:
                _reap(proc)
        except Exception as e:  # bind clash, import error, etc.
            last_err = e
            if proc is not None:
                _reap(proc)
        time.sleep(0.5)

    show_fatal(
        "Backend failed to start",
        "The solver engine couldn't be launched after several attempts.",
        [
            "Make sure no other copy of Wordle Strat-Console is already running.",
            f"If your firewall blocks localhost, allow it for this app.",
            "Set a custom port with the WSC_PORT environment variable and retry.",
            "Relaunch the app — the port is chosen automatically each run.",
        ],
        last_err,
    )
    return False


def _reap(proc) -> None:
    """Hard-kill a dev-server child and wait for it to exit (no lingering)."""
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def close_with_splash(window) -> None:
    """App-driven exit: show an inline 'shutting down' screen, then quit.

    Graceful path (no os._exit hard-kill): we paint the closing screen
    directly via load_html so there's no file-load race, give WebView2 a beat
    to repaint, then destroy the window and return — pywebview tears the
    process down cleanly on its own. """
    global APP_WINDOW
    APP_WINDOW = None
    # Stop the backend child first so the closing screen isn't fighting a
    # dying server, and the matrix file is released before the process ends.
    _stop_dev_server()
    try:
        closing_html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;height:100%;background:#0b0e14;color:#eef2f8;"
            "font-family:'Segoe UI',system-ui,sans-serif;display:flex;flex-direction:column;"
            "align-items:center;justify-content:center;gap:22px}"
            ".mark{width:84px;height:84px;border-radius:18px;display:flex;align-items:center;"
            "justify-content:center;background:#161d2b;border:1px solid #283142;font-size:40px;"
            "color:#34d27b}.title{letter-spacing:3px;font-size:18px;color:#9aa7bd}"
            ".title b{color:#eef2f8}.spin{width:34px;height:34px;border:3px solid #283142;"
            "border-top-color:#34d27b;border-radius:50%;animation:s .8s linear infinite}"
            "@keyframes s{to{transform:rotate(360deg)}}.st{font-size:12px;color:#6b788f}"
            "</style></head><body><div class='mark'>&#9670;</div>"
            "<div class='title'>WORDLE <b>STRAT-CONSOLE</b></div>"
            "<div class='spin'></div><div class='st' id='st'>Shutting down…</div></body></html>"
        )
        window.load_html(closing_html)
    except Exception:
        pass
    # Let the screen paint, then close gracefully (pywebview ends the process).
    time.sleep(0.9)
    try:
        window.destroy()
    except Exception:
        pass


# ── window + lifecycle ─────────────────────────────────────────────────────────
def main():
    global APP_WINDOW
    icon = assets_path("icon.ico") if os.path.exists(assets_path("icon.ico")) else None
    splash_path = assets_path("splash.html")

    # Pick an initial free port so the splash knows where to poll; boot() may
    # still choose a different one (and will tell the splash via __setPort).
    try:
        initial_port = find_free_port(PREFERRED_PORT)
    except RuntimeError as e:
        show_fatal(
            "No network port available",
            "Couldn't find a free localhost port to run the app on.",
            [
                "Close other apps that may be holding many ports.",
                "Relaunch — a port is picked automatically each run.",
            ],
            e,
        )
        return

    try:
        window = webview.create_window(
            title="Wordle Strat-Console",
            url=file_uri(assets_path("splash.html")) + f"#port={initial_port}",
            width=1240,
            height=840,
            min_size=(900, 640),
            resizable=True,
            fullscreen=False,
            text_select=False,
            confirm_close=False,
        )
    except Exception as e:
        show_fatal(
            "Could not open the window",
            "The app window couldn't be created — usually the WebView2 "
            "runtime is missing or blocked.",
            [
                "Install the Microsoft Edge WebView2 Runtime "
                "(https://developer.microsoft.com/microsoft-edge/webview2/).",
                "Relaunch the app afterwards.",
            ],
            e,
        )
        return

    # Frozen bundle: the HTTP backend must be reachable BEFORE the native
    # window is created, so the solver is verifiable even on a headless host
    # (or when WebView2 can't open a window). Start it now; boot() will simply
    # point the window at the already-live port. On a normal desktop the
    # window opens next and connects to the same port.
    if _is_frozen():
        try:
            start_frozen_server(initial_port)
        except Exception as e:  # pragma: no cover - defensive
            show_fatal(
                "Backend failed to start",
                "The solver engine couldn't be launched.",
                [
                    "Relaunch the app — the backend starts automatically.",
                    "If it repeats, the technical detail below is what to report.",
                ],
                e,
            )
            return

    APP_WINDOW = window

    _leaving = {"native": False}

    def _on_closed() -> None:
        # Native close box (no pre-close event in pywebview 6.2.1). Use a
        # graceful destroy so the process ends cleanly; guard against a
        # double fire if the app-driven Exit path already started teardown.
        if _leaving["native"]:
            return
        _leaving["native"] = True
        _stop_dev_server()  # release the matrix before the process ends
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    assert window is not None, "pywebview failed to create the window"
    window.events.closed += _on_closed

    # Expose entry points callable from JS as window.pywebview.api.*.
    def retry():
        boot(window)

    def exit_app():
        # App-driven exit shows the closing splash (see close_with_splash);
        # when the native box is used instead, _on_closed hard-kills directly.
        if _leaving["native"]:
            return
        _leaving["native"] = True
        close_with_splash(window)

    window.expose(retry, exit_app)

    # Start the heavy boot on a worker thread so the splash spinner keeps
    # animating while Python imports the backend. In the frozen bundle the
    # server is already up, so boot() only needs to point the window at it.
    def _start():
        threading.Thread(target=boot, args=(window,), daemon=True).start()

    try:
        webview.start(_start, gui=None, debug=False, icon=icon)
    except Exception as e:
        # A failed WebView2 init must not take the backend down: the frozen
        # server is already running (daemon thread) and will be torn down with
        # the process. Surface the reason, but the backend stays verifiable.
        show_fatal(
            "Could not start the interface",
            "The WebView2 interface failed to initialize.",
            [
                "Install/repair the Microsoft Edge WebView2 Runtime.",
                "Relaunch the app — the backend keeps running until you close it.",
            ],
            e,
        )


if __name__ == "__main__":
    main()