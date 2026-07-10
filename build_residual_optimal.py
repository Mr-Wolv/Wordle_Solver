"""Offline builder: identify the residual clusters where the greedy hard-mode
solver fails under the NYT 1-consonant+1-vowel hint rule, then precompute the
PROVEN-optimal minimax strategy (decision sub-tree) for each cluster.

Output: residual_optimal.json
  { "version": 1,
    "clusters": {
        "h,a": { "pool": [idx,...],
                 "strategy": { "<sorted,int,csv>": guess_idx, ... } },
        ...
    } }

The engine loads this (like turn1_cache.json) and only branches into the
specialist when the live pool is a subset of a registered cluster pool, under
hard mode + hints. Greedy remains the default hot path everywhere else.
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from Engine import WordleEngine
from _game import play_one_game   # exact current-engine behaviour (greedy)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "residual_optimal.json")

e = WordleEngine(); e.reset()
e._residual_optimal = {}   # identify GREEDY failures only (specialist disabled)
M = e.pm.matrix                       # 2315 x 2315 solution-space pattern ints
WORDS = e.lex.solution_words          # index = solution-space idx
N = len(WORDS)
CONS = set("bcdfghjklmnpqrstvwxyz")
VOW = set("aeiou")

def hint_pool(c, v):
    return frozenset(i for i, w in enumerate(WORDS) if c in w and v in w)

# IMPORTANT: the specialist must be DISABLED while we identify residuals, or
# play_one_game (which builds its own engine) would load the existing
# residual_optimal.json, close the clusters itself, report 0 residuals, and
# (below) overwrite the file with an empty one -- silently breaking hinted
# mode. Force an empty file on disk so the identification reflects true greedy
# behaviour. The freshly-built file is written at the end.
if os.path.exists(OUT):
    os.remove(OUT)

# ---- (1) identify residuals via the CURRENT engine (greedy, hard, hints) ----
SOL = pd.read_csv(os.path.join(ROOT, "valid_solutions.csv"))["word"].tolist()
residuals = []
for sec in SOL:
    w, t = play_one_game(sec, True, hints=True)
    if t > 6 or t <= 0:
        residuals.append(sec)
print(f"[identify] greedy hard+hints residuals ({len(residuals)}): {residuals}")

# ---- (2) enumerate valid (cons,vow) pairs for each residual word ----------
pairs = set()
for sec in residuals:
    cons = [c for c in dict.fromkeys(sec) if c in CONS]
    vow = [v for v in dict.fromkeys(sec) if v in VOW]
    for c in cons:
        for v in vow:
            pairs.add((c, v))
print(f"[pairs] {len(pairs)} distinct (cons,vow) clusters to solve")

# ---- (3) build the proven-optimal minimax strategy per cluster -------------
def build_strategy(pool, kmax=6):
    """Returns dict: frozenset(subpool) -> optimal guess idx (solution-space).
    Fills all reachable sub-pools as a side effect. Returns None if unsolvable."""
    table = {}
    def solve(S, k):
        S = frozenset(S)
        if S in table:
            return table[S]
        if len(S) == 1:
            g = next(iter(S)); table[S] = g; return g
        if k <= 1:
            table[S] = None; return None
        for g in S:                       # legal guesses = candidate set (hard)
            ok = True
            row = M[g]
            parts = {}
            for t in S:
                p = int(row[t])
                bucket = parts.get(p)
                if bucket is None:
                    parts[p] = {t}
                else:
                    bucket.add(t)
            for v in parts.values():
                if solve(v, k - 1) is None:
                    ok = False
                    break
            if ok:
                table[S] = g
                return g
        table[S] = None
        return None
    root = solve(pool, kmax)
    return table if root is not None else None

clusters = {}
t0 = time.time()
for (c, v) in sorted(pairs):
    pool = hint_pool(c, v)
    t1 = time.time()
    strat = build_strategy(pool, 6)
    dt = time.time() - t1
    if strat is None:
        print(f"  ! ({c},{v}) pool={len(pool)} UNSOLVABLE-optimal (skip)")
        continue
    # Store the full optimal sub-tree (sub-pool key -> optimal guess idx) plus
    # the root guess, so the engine can (a) pre-activate at turn 1 by playing
    # the root (steering onto the tree before greedy poisons the position)
    # and (b) look up the exact optimal guess once on-tree.
    ser = {}
    for sub, g in strat.items():
        if sub is None or g is None:
            continue
        ser[",".join(str(x) for x in sorted(sub))] = int(g)
    root_key = ",".join(str(x) for x in sorted(pool))
    clusters[f"{c},{v}"] = {
        "pool": sorted(pool),
        "root": ser[root_key],
        "strategy": ser,
    }
    print(f"  ({c},{v}) pool={len(pool):3d} nodes={len(strat):5d} "
          f"serialised={len(ser):5d}  [{dt:.2f}s]")
print(f"[build] total {time.time()-t0:.1f}s, {len(clusters)} clusters solved")

with open(OUT, "w") as f:
    json.dump({"version": 2, "clusters": clusters}, f)
sz = os.path.getsize(OUT)
print(f"[write] {OUT} ({sz/1024:.0f} KB)")
