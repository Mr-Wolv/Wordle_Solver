"""GUI play harness — plays the bundled app in a REAL browser, like a human.

Unlike the HTTP-only harness, this drives the actual DOM the user sees:
  * types the solver's suggested guess (keyboard),
  * CLICKS each tile to set its colour (absent/present/correct) — exactly what
    a human does when they read their Wordle result,
  * presses Enter to SUBMIT,
  * repeats until the board shows a win.
The app computes the colours from the clicks (same path a user triggers), so
this exercises the real frontend + backend colour flow, not a shortcut.

The EXE is launched DETACHED (server only; its own WebView2 window stays
uncreated), and Playwright (Chromium) is the visible "user" browser pointing at
http://127.0.0.1:<port>/. You watch it play in front of you.

Run:
    python probes/gui_playwright_play.py            # full ~47k games (slow, visible)
    WS_GUI_LIMIT=12 python probes/gui_playwright_play.py   # small watchable demo

Requires the bundle (build with `python build_game.py`) and Playwright Chromium.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(REPO, "dist", "Wordle-Strat-Console", "Wordle-Strat-Console.exe")
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
LIMIT = int(os.environ.get("WS_GUI_LIMIT", "0"))  # 0 = full corpus
HEADLESS = os.environ.get("WS_GUI_HEADLESS", "0") == "1"


def _api(port, path, payload=None, timeout=30):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET"
    )
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _pat_list(pat: int) -> list[int]:
    return [(pat // (3 ** i)) % 3 for i in range(5)]


def _load_words():
    import pandas
    from wordle_solver.utils import data_path
    raw = pandas.read_csv(data_path("valid_solutions.csv")).iloc[:, 0].tolist()
    words = [str(x).strip().lower() for x in raw]
    words = [w for w in words if w.isalpha() and len(w) == 5 and w != "word"]
    seen = set()
    out = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _hint_sets(word, budget, VOWELS, CONSONANTS):
    vs = sorted({c for c in word if c in VOWELS})
    cs = sorted({c for c in word if c in CONSONANTS})
    if budget == 0:
        return [[]]
    if budget == 1:
        return [[v] for v in vs] + [[c] for c in cs]
    out = [[v, c] for v in vs for c in cs]
    return out


def main():
    from playwright.sync_api import sync_playwright

    if not os.path.exists(EXE):
        print("WARN: bundle missing; building via build_game.py")
        subprocess.run([PY, "build_game.py"], check=True)

    # Free port + launch EXE detached (server only).
    port = None
    for off in range(200):
        p = 8800 + off
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                port = p
                break
            except OSError:
                continue
    assert port, "no free port"
    env = dict(os.environ, WSC_PORT=str(port))
    proc = subprocess.Popen(
        [EXE], cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                _api(port, "/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("bundled EXE HTTP API never came up")

        from wordle_solver.engine import WordleEngine
        from wordle_solver.engine.modes import VOWELS, CONSONANTS, MODE_ORDER
        engine = WordleEngine()
        words = _load_words()
        if LIMIT:
            words = words[:LIMIT]

        failures = []
        total = 0
        t0 = time.time()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=HEADLESS)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_selector("#board .row.active", timeout=30)

            def set_colors(colors):
                # Click each active tile `c` times to cycle to the target colour.
                for i, c in enumerate(colors):
                    for _ in range(c):
                        page.click(f'.board .row.active .tile[data-idx="{i}"]')

            def submit():
                page.keyboard.press("Enter")

            for mode_key in MODE_ORDER:
                budget = int(mode_key.split("_")[1])
                for secret in words:
                    hs_list = _hint_sets(secret, budget, VOWELS, CONSONANTS)
                    if not hs_list and budget == 2:
                        hs_list = _hint_sets(secret, 1, VOWELS, CONSONANTS)
                        play_key = mode_key.replace("_2", "_1")
                    else:
                        play_key = mode_key

                    worst = 0
                    for hs in hs_list:
                        _api(port, "/api/reset", {})
                        page.evaluate("document.getElementById('reset').click()")
                        if play_key.startswith("hard"):
                            page.evaluate(
                                "document.getElementById('hard').click()")
                        for letter in hs:
                            page.fill("#hint-letter", letter)
                            page.click("#hint-btn")
                        solved_turn = None
                        for turn in range(1, 7):
                            st = _api(port, "/api/state")
                            if st.get("solved"):
                                solved_turn = st.get("turn", turn)
                                break
                            guess = st["strat"][0]["word"]
                            # type the guess
                            page.click('.board .row.active', timeout=5)
                            page.keyboard.type(guess, delay=20)
                            colors = _pat_list(engine.calculate_pattern(guess, secret))
                            set_colors(colors)
                            submit()
                            # let the app render + the backend update
                            time.sleep(0.15)
                            res = _api(port, "/api/state")
                            if res.get("solved"):
                                solved_turn = turn
                                break
                        if solved_turn is None:
                            failures.append((secret, play_key, hs, "no-solve"))
                            worst = 7
                            break
                        worst = max(worst, solved_turn)
                    total += 1
                    if worst > 6:
                        failures.append((secret, play_key, "worst>6", worst))
                    if total % 50 == 0:
                        print(f"  {total} games, {len(failures)} fails, "
                              f"{time.time()-t0:.0f}s")
            browser.close()
        print(f"\nDONE: {total} games played in a real browser on the bundled EXE.")
        if failures:
            print(f"FAILURES ({len(failures)}):")
            for f in failures[:50]:
                print("  ", f)
            raise SystemExit(1)
        print("ALL GAMES SOLVED <=6 in the real GUI — faithful.")
    finally:
        try:
            _api(port, "/api/shutdown", timeout=5)
        except Exception:
            pass
        try:
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            subprocess.run(["taskkill", "/F", "/IM", "Wordle-Strat-Console.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    main()
