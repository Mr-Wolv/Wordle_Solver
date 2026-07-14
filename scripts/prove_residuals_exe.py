"""Prove the SHIPPED EXE (not a cache) solves every 'proven-residual' word.

Self-plays the 30 hardcoded seed words from enumerate_exhaustive._RESIDUAL_WORDS
through a running Wordle-Strat-Console EXE's HTTP API, in normal_0 and hard_0
(no-hint — the pathologically-slow minimax cases the report stamps via cache).
This closes the loop the report left open: it replays them LIVE through the
frozen artifact, asserting each closes in <=6. If the specialist trees weren't
bundled, these would fail.
"""
import json
import sys
import urllib.request
import urllib.error

from wordle_solver.engine import WordleEngine

ENGINE = WordleEngine()
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8753"

# Mirror of enumerate_exhaustive._RESIDUAL_WORDS (the 30 seeds behind 628).
SEEDS = [
    "baste", "bitty", "boxer", "chard", "cower", "dilly", "ditty", "foyer",
    "glade", "golly", "goner", "graze", "hatch", "homer", "hound", "hunch",
    "latch", "mound", "shale", "shave", "sight", "sower", "stash", "taffy",
    "tight", "valor", "vaunt", "width", "wight", "wound",
]


def _api(path, payload=None):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _play(secret, hard):
    _api("/api/reset", {})
    _api("/api/hard", {"on": hard})
    for _ in range(1, 7):
        st = _api("/api/state")
        if st.get("solved"):
            return st.get("turn", 1), True
        guess = st["strat"][0]["word"]
        # Authoritative coloring via the engine's own pattern function
        # (mirrors the frozen-bundle test; no hand-rolled two-pass logic).
        pat = ENGINE.calculate_pattern(guess, secret)
        colors = [(pat // (3 ** i)) % 3 for i in range(5)]
        try:
            res = _api("/api/submit", {"guess": guess, "colors": colors})
        except urllib.error.HTTPError as e:
            return None, False
        if res.get("solved"):
            return res.get("turn", 1), True
    return None, False


def main():
    fails = []
    for w in SEEDS:
        for hard in (False, True):
            turn, ok = _play(w, hard)
            tag = "hard" if hard else "normal"
            status = f"OK {turn}t" if ok else "FAIL"
            print(f"  {w:6} {tag:6} {status}")
            if not ok:
                fails.append((w, tag))
    print(f"\nSEEDS={len(SEEDS)} x2 domains = {len(SEEDS)*2} games")
    print(f"FAILURES: {len(fails)}")
    if fails:
        for w, t in fails:
            print(f"  FAIL {w} {t}")
        sys.exit(2)
    print("ALL 30 PROVEN-RESIDUAL WORDS SOLVED BY THE EXE ✓")


if __name__ == "__main__":
    main()
