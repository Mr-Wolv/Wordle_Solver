"""Offline builder: identify the residual clusters where the greedy hard-mode
solver fails under the NYT 1-consonant+1-vowel hint rule, then precompute the
PROVEN-optimal minimax strategy (decision sub-tree) for each cluster.

Output: residual_optimal.json
  { "version": 2,
    "clusters": {
        "h,a": { "pool": [idx,...], "root": idx,
                 "strategy": { "<sorted,int,csv>": guess_idx, ... } },
        ...
    } }

The engine loads this (like turn1_cache.json) and only branches into the
specialist when the live pool is a subset of a registered cluster pool, under
hard mode + hints. Greedy remains the default hot path everywhere else.

The exact minimax used here is ``wordle_solver.engine.patterns.build_optimal_table``
— the SINGLE SOURCE OF TRUTH shared with the live engine's ``_minimax_best``
and ``_residual_minimax``. That guarantees the offline artifact and the live
solver never drift apart.

Run:  python -m wordle_solver.generators.build_residual_optimal
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

from wordle_solver.engine import WordleEngine
from wordle_solver.engine.game import play_one_game
from wordle_solver.engine.patterns import build_optimal_table

from wordle_solver.utils import data_path

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = data_path("residual_optimal.json")

CONS = set("bcdfghjklmnpqrstvwxyz")
VOW = set("aeiou")


def hint_pool(words, c, v):
    return frozenset(
        i for i, w in enumerate(words) if c in w and v in w
    )


def main(dry_run: bool = False) -> dict:
    """Identify greedy hard+hints residuals and build the optimal table.

    When ``dry_run`` is True the on-disk artifact is NOT overwritten (use for
    CI verification that the recipe is reproducible without clobbering the
    committed baseline).
    """
    e = WordleEngine()
    e.reset()
    e._residual_optimal = {}  # identify GREEDY failures only (specialist off)
    M = e.pm.matrix  # 2315 x 2315 solution-space pattern ints
    WORDS = e.lex.solution_words

    # ---- (1) identify residuals via the CURRENT engine (greedy, hard, hints)
    sol_csv = data_path("valid_solutions.csv")
    SOL = pd.read_csv(sol_csv)["word"].tolist()
    residuals = []
    for sec in SOL:
        _w, t = play_one_game(sec, True, hints=True)
        if t > 6 or t <= 0:
            residuals.append(sec)
    print(f"[identify] greedy hard+hints residuals ({len(residuals)}): {residuals}")

    # ---- (2) enumerate valid (cons,vow) pairs for each residual word
    pairs = set()
    for sec in residuals:
        cons = [c for c in dict.fromkeys(sec) if c in CONS]
        vow = [v for v in dict.fromkeys(sec) if v in VOW]
        for c in cons:
            for v in vow:
                pairs.add((c, v))
    print(f"[pairs] {len(pairs)} distinct (cons,vow) clusters to solve")

    # ---- (3) build the proven-optimal minimax strategy per cluster
    #        (shared solver -> no drift vs the live engine)
    clusters: dict[str, dict] = {}
    t0 = time.time()
    for (c, v) in sorted(pairs):
        pool = hint_pool(WORDS, c, v)
        t1 = time.time()
        table = build_optimal_table(M, pool, kmax=6)
        dt = time.time() - t1
        if not table:
            print(f"  ! ({c},{v}) pool={len(pool)} UNSOLVABLE-optimal (skip)")
            continue
        ser = {
            ",".join(str(x) for x in sorted(sub)): int(g)
            for sub, g in table.items()
            if g is not None
        }
        root_key = ",".join(str(x) for x in sorted(pool))
        clusters[f"{c},{v}"] = {
            "pool": sorted(pool),
            "root": ser[root_key],
            "strategy": ser,
        }
        print(
            f"  ({c},{v}) pool={len(pool):3d} nodes={len(table):5d} "
            f"serialised={len(ser):5d}  [{dt:.2f}s]"
        )
    print(f"[build] total {time.time()-t0:.1f}s, {len(clusters)} clusters solved")

    data = {"version": 2, "clusters": clusters}
    if dry_run:
        print(f"[dry-run] not writing {OUT} ({len(clusters)} clusters)")
        return data
    with open(OUT, "w") as f:
        json.dump(data, f)
    sz = os.path.getsize(OUT)
    print(f"[write] {OUT} ({sz/1024:.0f} KB)")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="build the table in memory but do NOT overwrite the committed artifact",
    )
    args = ap.parse_args()
    main(dry_run=args.dry_run)
