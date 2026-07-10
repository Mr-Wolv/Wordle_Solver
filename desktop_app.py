"""Wordle Strat-Console — desktop wrapper.

Runs the FastAPI web backend (``web_server``) in a background thread and
opens the DOM frontend (``web/``) inside a native **pywebview** window.

Runtime robustness (the point of this rewrite):
  * PORT is picked at runtime from a free socket (env WSC_PORT overrides the
    preferred base). No more "port 8753 already in use" dead ends.
  * The backend is started with RETRY across several candidate ports; a
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
import socket
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

ROOT = Path(__file__).resolve().parent
PREFERRED_PORT = int(os.environ.get("WSC_PORT", "8753"))
MAX_ATTEMPTS = 6
POLL_TIMEOUT = 20.0  # generous: first /api/state triggers the lazy matrix load

APP_WINDOW = None  # set after window creation; used by the crash handler


# ── port selection ──────────────────────────────────────────────────────────
def _find_free_port(preferred: int) -> int:
    """Return the first free 127.0.0.1 port at or after ``preferred``."""
    for off in range(MAX_ATTEMPTS):
        p = preferred + off
        if p > 65535:
            break
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(
        f"no free localhost port found near {preferred} "
        f"(tried {MAX_ATTEMPTS} ports)."
    )


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
<meta name="viewport" content="width=device-width,initial-scale=1">
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


# ── backend boot (with retry) ─────────────────────────────────────────────────
def boot(window) -> bool:
    """Start the backend on a runtime-chosen free port, retrying on failure.

    Returns True on success (window swapped to the live app) or False after
    exhausting attempts (a fatal card with a Retry button is shown).
    """
    import web_server  # heavy import (numpy/pandas/fastapi) — runs BEHIND the splash
    import uvicorn

    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            port = _find_free_port(PREFERRED_PORT + attempt - 1)
            # Tell the splash which port to poll for status (it may differ
            # from the one it was opened with).
            try:
                window.evaluate_js(f"if(window.__setPort)window.__setPort({port});")
            except Exception:
                pass
            web_server.set_load_status("Loading word matrix…")
            # Tag the engine with this port so its turn-1 cache file is
            # per-instance (two dev instances never write the same file).
            try:
                web_server.engine._port = port
            except Exception:
                pass
            web_server.set_load_status("Warming up solver…")
            # NOTE: we let uvicorn bind the port itself (port=port), NOT a
            # pre-bound fd. uvicorn's fd path does socket.fromfd(..., AF_UNIX)
            # internally, which is unavailable on Windows and crashes the boot.
            # Multi-instance safety comes from the runtime free-port scan above
            # (each instance claims its own 127.0.0.1 port) plus the per-instance
            # cache keyed by that port — both verified.
            cfg = uvicorn.Config(
                web_server.app, host="127.0.0.1", port=port, log_level="error"
            )
            threading.Thread(
                target=lambda: uvicorn.Server(cfg).run(), daemon=True
            ).start()
            if _wait_for_server(port):
                # Drive ONE real turn-1 computation so the (per-instance) cache
                # is baked before the user plays — keeps the first move instant.
                web_server.set_load_status("Compiling suggestions…")
                try:
                    web_server.engine.get_suggestions()
                    web_server.engine.get_suggestions(is_hard_mode=True)
                except Exception:
                    pass
                web_server.set_load_status("Ready")
                window.load_url(f"http://127.0.0.1:{port}/")
                return True
            last_err = RuntimeError(
                f"backend accepted no connections on port {port} "
                f"within {POLL_TIMEOUT:.0f}s"
            )
        except Exception as e:  # bind clash, import error, etc.
            last_err = e
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


def close_with_splash(window) -> None:
    """App-driven exit: show an inline 'shutting down' screen, then quit.

    Graceful path (no os._exit hard-kill): we paint the closing screen
    directly via load_html so there's no file-load race, give WebView2 a beat
    to repaint, then destroy the window and return — pywebview tears the
    process down cleanly on its own. """
    global APP_WINDOW
    APP_WINDOW = None
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
    icon = str(ROOT / "icon.ico") if (ROOT / "icon.ico").exists() else None
    splash_path = str(ROOT / "splash.html")

    # Pick an initial free port so the splash knows where to poll; boot() may
    # still choose a different one (and will tell the splash via __setPort).
    try:
        initial_port = _find_free_port(PREFERRED_PORT)
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
            url=file_uri(str(ROOT / "splash.html")) + f"#port={initial_port}",
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

    APP_WINDOW = window

    _leaving = {"native": False}

    def _on_closed() -> None:
        # Native close box (no pre-close event in pywebview 6.2.1). Use a
        # graceful destroy so the process ends cleanly; guard against a
        # double fire if the app-driven Exit path already started teardown.
        if _leaving["native"]:
            return
        _leaving["native"] = True
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
    # animating while Python imports the backend.
    def _start():
        threading.Thread(target=boot, args=(window,), daemon=True).start()

    try:
        webview.start(_start, gui=None, debug=False, icon=icon)
    except Exception as e:
        show_fatal(
            "Could not start the interface",
            "The WebView2 interface failed to initialize.",
            [
                "Install/repair the Microsoft Edge WebView2 Runtime.",
                "Relaunch the app.",
            ],
            e,
        )


if __name__ == "__main__":
    main()
