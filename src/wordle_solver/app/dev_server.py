"""Wordle Strat-Console — *dev* server.

A developer-friendly launcher for the web backend. Its whole reason for
existing is the trap we hit before: a hardcoded ``port=8000`` ``uvicorn``
process that lingered after its parent died, holding the (memory-mapped)
word matrix open and blocking rebuilds.

So this launcher guarantees three things:
  1. CONFLICT-FREE START — it binds the first free 127.0.0.1 port at/after
     the preferred one (env ``WSC_PORT`` overrides; ``0`` → any free port),
     via :func:`wordle_solver.utils.find_free_port`. No "address already in
     use" dead ends, no port wars with a second dev instance.
  2. SESSION-BOUND (primary) — when launched with ``--parent-pid`` (the
     desktop app does this), the server watches its parent and self-exits
     the instant the game session ends, so it can never outlive the window
     and re-lock the matrix. A ``POST /api/shutdown`` endpoint lets the
     parent request a clean exit too.
  3. AUTO-DISABLE (safety net) — even standalone, it shuts down on a
     watchdog so it can never linger:
       * IDLE timeout: no request for ``--idle`` seconds (default 30 min),
       * and/or a hard UPTIME cap ``--max-age`` seconds (default 2 h),
     whichever comes first. On shutdown it logs the port so the dev knows
     the slot is free again. A clean ``sys.exit`` (not ``os._exit``) lets
     Python release the mmap'd matrix before the process ends.

Run:
    python -m wordle_solver.app.dev_server            # port 8753+, 30m idle / 2h cap
    python -m wordle_solver.app.dev_server --port 0   # any free port
    python -m wordle_solver.app.dev_server --parent-pid $$   # die with parent
    python -m wordle_solver.app.dev_server --idle 600 --max-age 0   # 10m idle, no cap
    python -m wordle_solver.app.dev_server --no-auto-shutdown   # behave like the old server
"""
from __future__ import annotations

import argparse
import atexit
import os
import sys
import threading
import time

import uvicorn

from wordle_solver.utils import find_free_port
from wordle_solver.app import web_server


def _parent_alive(pid: int) -> bool:
    """True while ``pid`` is a live process.

    We can't use ``os.kill(pid, 0)`` on Windows: there it falsely reports a
    killed process as still alive, so a session-bound server would never
    notice its parent died. Instead we open a handle and read the exit code
    (``STILL_ACTIVE == 259`` means running); a missing/finished process is
    treated as dead. Non-Windows falls back to the portable ``os.kill`` probe.
    """
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)  # signal 0 = existence check, no real signal sent
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False  # process doesn't exist
    try:
        exit_code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return False  # couldn't read => treat as dead
    finally:
        kernel32.CloseHandle(handle)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Wordle Strat-Console dev server")
    p.add_argument(
        "--port", type=int, default=int(os.environ.get("WSC_PORT", "8753")),
        help="preferred 127.0.0.1 port; scans upward for a free one "
             "(0 = any free port). Env WSC_PORT overrides.",
    )
    p.add_argument(
        "--host", default="127.0.0.1",
        help="bind host (default 127.0.0.1 — localhost only).",
    )
    p.add_argument(
        "--parent-pid", type=int, default=0,
        help="watch this process id and self-exit the moment it dies "
             "(used by the desktop app to bind server life to the window).",
    )
    p.add_argument(
        "--idle", type=float, default=1800.0,
        help="auto-shutdown after this many seconds of inactivity "
             "(default 1800 = 30 min; 0 disables idle shutdown).",
    )
    p.add_argument(
        "--max-age", type=float, default=7200.0,
        help="hard auto-shutdown after this many seconds of uptime "
             "(default 7200 = 2 h; 0 disables the uptime cap).",
    )
    p.add_argument(
        "--no-auto-shutdown", action="store_true",
        help="disable the watchdog entirely (old behaviour — not recommended; "
             "a lingering process can lock the matrix file).",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    auto = not args.no_auto_shutdown
    session_bound = args.parent_pid > 0

    port = find_free_port(args.port)
    web_server.configure_engine(port)

    # liveness tracking for the watchdog
    lock = threading.Lock()
    last_activity = {"t": time.time()}
    boot_ts = time.time()

    @web_server.app.middleware("http")
    async def _touch(request, call_next):
        # mark activity on every accepted request (cheap, lock held briefly)
        with lock:
            last_activity["t"] = time.time()
        return await call_next(request)

    server = uvicorn.Server(
        uvicorn.Config(web_server.app, host=args.host, port=port, log_level="info")
    )

    def _trigger(reason: str) -> None:
        print(f"[dev-server] {reason} — auto-shutting down (was on :{port})", flush=True)
        server.should_exit = True

    # The watchdog ALWAYS runs: it must always honor the two safety-critical
    # signals — parent death (--parent-pid) and an explicit /api/shutdown —
    # even when --no-auto-shutdown is set. Idle/uptime caps are the only parts
    # gated behind `auto`.
    def _should_stop() -> tuple[bool, str]:
        """Return (stop, reason). `stop` is True only for a real shutdown
        signal. While the server hasn't started yet we return (False, "") and
        keep looping — the watchdog must NOT exit early, or the lifecycle
        guarantees (die-with-parent, /api/shutdown, idle, uptime) would all be
        silently disabled."""
        if session_bound and not _parent_alive(args.parent_pid):
            return True, f"parent pid {args.parent_pid} ended"
        if web_server.shutdown_requested:
            return True, "shutdown requested via /api/shutdown"
        if not server.started:
            return False, ""  # not up yet — keep watching
        if auto:
            with lock:
                idle_for = time.time() - last_activity["t"]
            age = time.time() - boot_ts
            if args.idle and idle_for >= args.idle:
                return True, f"idle {idle_for:.0f}s ≥ {args.idle:.0f}s"
            if args.max_age and age >= args.max_age:
                return True, f"uptime {age:.0f}s ≥ {args.max_age:.0f}s"
        return False, ""

    def _watchdog() -> None:
        while True:
            time.sleep(2)
            if server.should_exit:
                return
            stop, reason = _should_stop()
            if stop:
                _trigger(reason)
                return

    threading.Thread(target=_watchdog, daemon=True).start()

    # Speed up first real move by warming the per-instance cache, and keep
    # the splash status channel live (the desktop splash polls /api/load-status).
    web_server.set_load_status("Loading word matrix…")
    try:
        web_server.engine.get_suggestions()
        web_server.engine.get_suggestions(is_hard_mode=True)
    except Exception:
        pass
    web_server.set_load_status("Ready")

    def _bye() -> None:
        print(f"[dev-server] stopped — port :{port} is free again.", flush=True)

    atexit.register(_bye)

    scope = "session-bound(parent)" if session_bound else (
        "idle+uptime" if auto else "no auto-shutdown"
    )
    idle_s = "off" if (not auto or not args.idle) else f"{args.idle:.0f}s"
    age_s = "off" if (not auto or not args.max_age) else f"{args.max_age:.0f}s"
    print(
        f"[dev-server] running on http://{args.host}:{port}  "
        f"(lifecycle: {scope}; idle={idle_s}, uptime-cap={age_s})",
        flush=True,
    )
    try:
        server.run()
    finally:
        # clean teardown: release the matrix mmap before the process exits
        # so no dangling fd is GC'd at interpreter shutdown.
        try:
            from wordle_solver.engine.engine import _matrix

            if _matrix is not None:
                _matrix.close()
        except Exception:
            pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
