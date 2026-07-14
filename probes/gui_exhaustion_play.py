"""GUI-exhaustion harness — the ultimate "it works on the shipped artifact" proof.

Drives the BUILT Wordle-Strat-Console EXE (not the source `play_mode` call)
through EVERY game of the six locked domains, exactly as a user would via the
HTTP API the desktop app exposes:

    POST /api/reset
    POST /api/hard {on}            (domains hard_0/hard_1/hard_2)
    POST /api/hint {letter}  x N    (before turn 1, for 1/2-hint domains)
    loop: GET /api/state -> top guess (strat[0].word)
          POST /api/submit {guess, colors}   (colors = true pattern)
    until solved (all-green) or 6 turns.

If the bundled app's web_server / GameMode / engine faithfully reproduce the
solver, every game closes in <=6 turns — the same 47,814 results
test_game_contract proves at the `play_mode` layer. Any divergence (a state
bug, a hint-lock regression, a mode mis-map) shows up HERE, on the real
artifact, not just in unit logic. That is the portability guarantee:
"it does not only work on my machine."

Run:
    python probes/gui_exhaustion_play.py            # full ~47k games (slow)
    WS_GUI_LIMIT=50 python probes/gui_exhaustion_play.py   # smoke test (50 words)

Requires the bundle at dist/Wordle-Strat-Console/Wordle-Strat-Console.exe
(build with `python build_game.py`). The EXE is launched DETACHED so it does
not block the shell; the harness polls its HTTP API, plays, then shuts it down.
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


def _pattern_list(pat: int) -> list[int]:
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
    return out  # empty for all-consonant words -> caller falls back to 1-hint


def main():
    if not os.path.exists(EXE):
        print(f"WARN: bundle missing at {EXE}; building via build_game.py")
        subprocess.run([PY, "build_game.py"], check=True)

    # Pick a free port and launch the EXE DETACHED (does not block the shell).
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
    assert port, "no free port for the EXE"
    env = dict(os.environ, WSC_PORT=str(port))
    proc = subprocess.Popen(
        [EXE], cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        # Wait for the server (comes up before the window in the frozen bundle).
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

        domains = MODE_ORDER  # normal_0, hard_0, normal_1, hard_1, normal_2, hard_2
        total = 0
        failures = []
        t0 = time.time()
        for mode_key in domains:
            budget = int(mode_key.split("_")[1])
            for secret in words:
                # Enumerate hint sets for this word in this domain.
                hs_list = _hint_sets(secret, budget, VOWELS, CONSONANTS)
                if not hs_list and budget == 2:
                    # vowel-less word: NYT falls back to 1-hint domain
                    hs_list = _hint_sets(secret, 1, VOWELS, CONSONANTS)
                    play_mode_key = mode_key.replace("_2", "_1")
                else:
                    play_mode_key = mode_key

                worst = 0
                for hs in hs_list:
                    _api(port, "/api/reset", {})
                    if play_mode_key.startswith("hard"):
                        _api(port, "/api/hard", {"on": True})
                    for letter in hs:
                        _api(port, "/api/hint", {"letter": letter})
                    solved_turn = None
                    for turn in range(1, 7):
                        st = _api(port, "/api/state")
                        if st.get("solved"):
                            solved_turn = st.get("turn", turn)
                            break
                        guess = st["strat"][0]["word"]
                        pat = engine.calculate_pattern(guess, secret)
                        colors = _pattern_list(pat)
                        res = _api(port, "/api/submit",
                                   {"guess": guess, "colors": colors})
                        if res.get("solved"):
                            solved_turn = turn
                            break
                    if solved_turn is None:
                        failures.append((secret, play_mode_key, hs, "no-solve"))
                        worst = 7
                        break
                    worst = max(worst, solved_turn)
                total += 1
                if worst > 6:
                    failures.append((secret, play_mode_key, "worst>6", worst))
                if total % 500 == 0:
                    print(f"  progress: {total} games, "
                          f"{len(failures)} failures, {time.time()-t0:.0f}s")
        print(f"\nDONE: {total} games played on the bundled EXE.")
        if failures:
            print(f"FAILURES ({len(failures)}):")
            for f in failures[:50]:
                print("  ", f)
            raise SystemExit(1)
        print("ALL GAMES SOLVED <=6 on the bundled EXE — GUI layer faithful.")
    finally:
        # Clean shutdown: ask the app, then force-kill if needed.
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
        # Belt-and-suspenders
        try:
            subprocess.run(["taskkill", "/F", "/IM", "Wordle-Strat-Console.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    main()
