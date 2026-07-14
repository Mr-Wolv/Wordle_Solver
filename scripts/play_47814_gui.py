#!/usr/bin/env python3
"""Drive the REAL Wordle Strat-Console UI through all 47,814 scenarios live.

This is a visual durability check: it opens (or attaches to) the game in a
real Chromium window and replays, through genuine user gestures, the exact
same (secret, domain, hint-set) set that the exhaustive pytest gate proves.
For each scenario it:

  1. resets the game (POST /api/reset),
  2. establishes the locked domain (hard toggle + optional hint letters),
  3. types the UI's own top SOLVE suggestion onto the board,
  4. cycles the real tiles to the true Wordle color, presses Enter,
  5. repeats until the UI reports a win (or 6 moves exhausted),
  6. records WIN / FAIL (a FAIL = UI didn't solve within 6 moves).

Because the gate's play_mode plays the same rank-0 suggestion the UI shows in
SOLVE[0], and ColabWordle coloring is deterministic, the gesture sequence is
behaviorally identical to the proven gate — but now rendered through the real
DOM, so you SEE it work (and catch any UI-only regression the headless gate
couldn't).

Run:
    python scripts/play_47814_gui.py                 # dev server, 2000 games, live
    python scripts/play_47814_gui.py --all           # full 47,814 marathon
    python scripts/play_47814_gui.py --limit 5000 --port 8753
    python scripts/play_47814_gui.py --target exe --exe dist/.../Wordle-Strat-Console.exe

WARNING: a full run is a real browser macro. 47,814 * ~6 guesses * (typing +
tile-cycling + submit) is many hours of wall-clock. Watch it, then walk away;
it reports progress + any FAILs to docs/gui_play_report.json and the console.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# make the project importable (WordleEngine, enumeration contract)
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from wordle_solver.engine import WordleEngine  # noqa: E402
from wordle_solver.engine.modes import VOWELS, CONSONANTS, MODE_ORDER  # noqa: E402
# reuse the EXACT enumeration the exhaustive gate proves (single source of truth)
from wordle_solver.tools.enumerate_exhaustive import pairs_for_word  # noqa: E402

STATE_URL = "{base}/api/state"
RESET_URL = "{base}/api/reset"
HARD_URL = "{base}/api/hard"
HINT_URL = "{base}/api/hint"
SUBMIT_URL = "{base}/api/submit"

COLORS = {"absent": 0, "present": 1, "correct": 2}


def _free_port(preferred: int = 8753, attempts: int = 50) -> int:
    for off in range(attempts):
        p = preferred + off
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free localhost port")


def _find_dev_server() -> str | None:
    """Return a reachable dev-server base URL, or None if not running."""
    import urllib.request

    for p in range(8753, 8800):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/state", timeout=0.4):
                return f"http://127.0.0.1:{p}"
        except Exception:
            continue
    return None


def _start_dev_server() -> tuple[str, subprocess.Popen]:
    import wordle_solver.app.web_server as backend

    port = _free_port()
    backend.configure_engine(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "wordle_solver.app.dev_server",
         "--port", str(port), "--no-auto-shutdown"],
        cwd=REPO_ROOT,
    )
    # wait until it answers
    import urllib.request

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.5)
            return f"http://127.0.0.1:{port}", proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("dev server exited on boot")
            time.sleep(0.3)
    raise RuntimeError("dev server did not come up")


def _start_exe(exe_path: str) -> tuple[str, subprocess.Popen]:
    # Frozen bundle: pin a port, launch, discover via the load sequence.
    port = _free_port(8899)
    env = dict(os.environ, WSC_PORT=str(port))
    folder = os.path.dirname(exe_path)
    proc = subprocess.Popen([exe_path], cwd=folder, env=env)
    import urllib.request

    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.5)
            return f"http://127.0.0.1:{port}", proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("exe exited on boot")
            time.sleep(0.3)
    raise RuntimeError("exe did not come up")


def _post(base: str, path: str, payload=None, timeout: float = 20):
    import urllib.request

    url = f"{base}{path}"
    method = "GET" if path.endswith("/api/state") else "POST"
    data = json.dumps(payload or {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _color_for(guess: str, secret: str) -> list[int]:
    """Colab/NYT Wordle coloring (two-pass greens then yellows)."""
    res = [0] * 5
    sec = list(secret)
    for i, (g, s) in enumerate(zip(guess, secret)):
        if g == s:
            res[i] = 2
            sec[i] = "\0"
    for i, g in enumerate(guess):
        if res[i] == 2:
            continue
        if g in sec:
            res[i] = 1
            sec[sec.index(g)] = "\0"
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Live GUI replay of all 47,814 scenarios.")
    ap.add_argument("--target", choices=["dev", "exe"], default="dev",
                    help="dev server (default) or frozen exe")
    ap.add_argument("--exe", default=None, help="path to frozen exe (target=exe)")
    ap.add_argument("--port", type=int, default=0,
                    help="attach to an already-running dev server on this port")
    ap.add_argument("--limit", type=int, default=2000,
                    help="max scenarios to play (default 2000; the rest are skipped)")
    ap.add_argument("--all", action="store_true", help="play all 47,814 (marathon)")
    ap.add_argument("--headless", action="store_true",
                    help="hide the browser window (still real DOM, just no visible UI)")
    ap.add_argument("--report", default=os.path.join(REPO_ROOT, "docs",
                    "gui_play_report.json"), help="report output path (workspace)")
    args = ap.parse_args()

    limit = None if args.all else args.limit

    # 1) bring up / attach the backend
    proc = None
    if args.target == "exe":
        if not args.exe:
            ap.error("--exe required for target=exe")
        base, proc = _start_exe(args.exe)
    else:
        if args.port:
            base = f"http://127.0.0.1:{args.port}"
        else:
            existing = _find_dev_server()
            base, proc = (existing, None) if existing else _start_dev_server()
    print(f"[play] backend: {base}")

    # 2) bring up the real browser
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=args.headless)
    page = browser.new_page()
    page.goto(base)
    page.wait_for_function(
        "() => document.documentElement.dataset.appReady === '1'", timeout=15000)
    print("[play] browser ready — you should see the game window.")

    # 3) enumerate the EXACT scenario set the gate proves
    engine = WordleEngine()
    words = engine.lex.solution_words  # 2,315 — identical to the gate's _load_words()
    scenarios = []  # (secret, mode_key, hint_letters)
    for w in words:
        for mode_key in MODE_ORDER:
            for _, m, hs in pairs_for_word(w, mode_key):
                scenarios.append((w, mode_key, hs if hs else None))

    total = len(scenarios)
    print(f"[play] enumerated {total} scenarios (the full gate set). "
          f"limit={limit if limit else 'ALL'}")
    if limit and limit < total:
        scenarios = scenarios[:limit]
        print(f"[play] playing first {len(scenarios)} (set --all for the full marathon).")

    fails: list[dict] = []
    started = time.time()
    played = 0
    try:
        for (secret, mode_key, hints) in scenarios:
            played += 1
            ok = _play_one(page, base, engine, secret, mode_key, hints)
            if not ok:
                fails.append({"secret": secret, "mode": mode_key,
                              "hints": hints, "result": "FAIL (>6 or no win)"})
            if played % 50 == 0:
                el = time.time() - started
                rate = played / el if el else 0
                eta = (total - played) / rate if (limit is None and rate) else None
                tail = f" ETA~{eta/60:.0f}m" if eta else ""
                print(f"[play] {played}/{len(scenarios)} "
                      f"({rate:.1f} g/s) fails={len(fails)}{tail}")
    except KeyboardInterrupt:
        print("\n[play] interrupted by user — saving partial report.")
    finally:
        # report (workspace)
        report = {
            "total_enumerated": total,
            "played": played,
            "fails": fails,
            "pass_rate": (played - len(fails)) / played if played else 0.0,
            "elapsed_sec": round(time.time() - started, 1),
            "backend": base,
        }
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"[play] report -> {args.report}")
        if fails:
            print(f"[play] {len(fails)} FAILURES:")
            for f_ in fails[:30]:
                print("   ", f_)
        else:
            print(f"[play] ALL {played} PLAYED GAMES SOLVED ✓")
        browser.close()
        pw.stop()
        if proc is not None:
            try:
                _post(base, "/api/shutdown")
            except Exception:
                pass
            proc.wait(timeout=5)
    return 0 if not fails else 2


def _play_one(page, base: str, engine: WordleEngine,
              secret: str, mode_key: str, hints) -> bool:
    """Play one scenario through the REAL UI; return True if UI reports a win."""
    # Fresh game: clear the process-global engine, then reload the page so the
    # board re-renders a clean active row with empty .entry tiles (matching a
    # real "new game" — the e2e fixtures also reload per game).
    _post(base, "/api/reset")
    page.goto(base)
    page.wait_for_function(
        "() => document.documentElement.dataset.appReady === '1'", timeout=15000)
    hard = mode_key.startswith("hard")
    _post(base, "/api/hard", {"on": hard})
    if hints:
        for h in hints:
            _post(base, "/api/hint", {"letter": h})

    for turn in range(1, 7):
        st = _post(base, "/api/state")
        if st.get("solved"):
            return True
        # the UI's own top suggestion (identical to what play_mode picks)
        guess = st["strat"][0]["word"]
        colors = _color_for(guess, secret)
        # --- real user gestures (faithful copy of tests/test_workflows_web.py
        #     _set_word/_set/_submit, which pass under CI) ---
        page.keyboard.type(guess, delay=10)
        page.wait_for_selector(".board .row.active .tile.entry")
        for i, c in enumerate(colors):
            btn = page.locator(".board .row.active .tile.entry").nth(i)
            for _ in range(3):
                label = btn.get_attribute("aria-label") or ""
                cur = label.split(",")[1].strip().split()[0] if "," in label else ""
                cur_state = COLORS.get(cur, -1)
                if cur_state == c:
                    break
                btn.click()
        page.keyboard.press("Enter")
        page.wait_for_function(
            "() => !window.app || window.app.busy === false", timeout=8000)
    st = _post(base, "/api/state")
    return bool(st.get("solved"))


if __name__ == "__main__":
    raise SystemExit(main())
