"""Visible-play driver: plays the real EXE in front of you and proves it.

Launches the Wordle-Strat-Console EXE VISIBLY (its own WebView2 window
appears on your desktop), then drives real moves through its HTTP API. The
API is the same backend the window uses, so the visible window updates live
as each guess is submitted — you watch it play.

After a few moves it captures a MID-GAME screenshot (D:/gui_playing.png) so
you have eyeball proof the board fills with colored tiles. It plays a small
number of games (WS_GUI_LIMIT words) then stops — this is a demo/proof, not
the full ~47k exhaustion run (that runs headless separately).

Run:  python probes/gui_visible_play.py
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
LIMIT = int(os.environ.get("WS_GUI_LIMIT", "8"))  # words to play (demo)


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


def _screenshot(port, path):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            p = b.new_page()
            p.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            p.wait_for_timeout(1200)
            p.screenshot(path=path)
            b.close()
        return True
    except Exception as e:
        print(f"  (screenshot failed: {e})")
        return False


def main():
    if not os.path.exists(EXE):
        print("WARN: bundle missing; building")
        subprocess.run([PY, "build_game.py"], check=True)

    port = None
    for off in range(200):
        p = 8811 + off
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                port = p
                break
            except OSError:
                continue
    assert port, "no free port"

    # Launch VISIBLY — the EXE's own WebView2 window appears on your desktop.
    env = dict(os.environ, WSC_PORT=str(port))
    proc = subprocess.Popen(
        [EXE], cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
            raise RuntimeError("EXE API never came up")

        from wordle_solver.engine import WordleEngine
        from wordle_solver.utils import data_path
        import pandas
        engine = WordleEngine()
        raw = pandas.read_csv(data_path("valid_solutions.csv")).iloc[:, 0].tolist()
        words = [str(x).strip().lower() for x in raw
                 if str(x).strip().isalpha() and len(str(x).strip()) == 5]
        words = words[:LIMIT]

        print(f"EXE visible on your desktop at http://127.0.0.1:{port}/ — watch it play.")
        played = 0
        for secret in words:
            _api(port, "/api/reset", {})
            print(f"\n=== playing '{secret}' (answer hidden from app) ===")
            solved_turn = None
            for turn in range(1, 7):
                st = _api(port, "/api/state")
                if st.get("solved"):
                    solved_turn = st.get("turn", turn)
                    break
                guess = st["strat"][0]["word"]
                pat = engine.calculate_pattern(guess, secret)
                colors = _pat_list(pat)
                res = _api(port, "/api/submit", {"guess": guess, "colors": colors})
                print(f"  turn {turn}: guess {guess.upper()} -> "
                      f"{''.join('G' if c == 2 else 'Y' if c == 1 else '.' for c in colors)}")
                if res.get("solved"):
                    solved_turn = turn
                    break
                time.sleep(0.4)  # let the visible window repaint
            played += 1
            if played == 3:
                # Capture a mid-session screenshot so you can eyeball progress.
                if _screenshot(port, "D:/gui_playing.png"):
                    print("  >> screenshot saved to D:/gui_playing.png (eyeball it)")
            print(f"  -> SOLVED in {solved_turn} turns" if solved_turn else "  -> FAILED")
        print(f"\nDONE: played {played} games visibly via the real EXE window.")
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
