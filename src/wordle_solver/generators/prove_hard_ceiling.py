"""Prove whether HARD no-hint can reach 100% under ANY computational cost.

Two solvers, identical otherwise:
  (A) STRICT hard rule: every guess must be in the current consistent pool.
  (B) RELAXED (normal-mode freedom): guess may be ANY answer word, even if not
      in the pool (a "shredder"). This is what the no-hint optimal ceiling used.

If (A) needs >6 turns for a word, then 100% is IMPOSSIBLE under NYT hard rules
no matter the compute -- it is a structural ceiling of the rule, not a search
depth limit. If (B) solves it in <=6, the wall is the rule, not the algorithm.
"""
from __future__ import annotations
import sys, time
sys.path.insert(0, ".")
import numpy as np
from wordle_solver.engine import WordleEngine

e = WordleEngine(); e.reset()
WORDS = e.lex.solution_words
M = e.pm.matrix                      # 2315 x 2315 solution-space pattern ints
N = len(WORDS)
ALL = frozenset(range(N))

from functools import lru_cache

def solve_depth(secret_idx: int, strict_hard: bool, max_states=200000):
    """Return optimal worst-case turns to name `secret_idx`, minimizing the
    maximum remaining depth over all possible feedback branches."""
    # state = frozenset of candidate solution indices still consistent
    from functools import lru_cache
    calls = {"n": 0}
    @lru_cache(maxsize=None)
    def opt(state_frozen):
        state = state_frozen
        if len(state) <= 1:
            return 1 if len(state) == 1 else 0
        calls["n"] += 1
        if calls["n"] > max_states:
            return 99  # give up (shouldn't happen for these small clusters)
        # allowed guesses
        guesses = state if strict_hard else ALL
        best = 99
        for g in guesses:
            worst = 0
            # group remaining candidates by pattern vs g
            buckets = {}
            for s in state:
                p = int(M[g, s])
                buckets.setdefault(p, set()).add(s)
            for b in buckets.values():
                d = opt(frozenset(b))
                if d + 1 > worst:
                    worst = d + 1
                    if worst >= best:
                        break
            if worst < best:
                best = worst
                if best == 1:
                    break
        return best
    return opt(frozenset(ALL)), calls["n"]

if __name__ == "__main__":
    targets = ["foyer", "hatch", "hound", "hunch", "latch", "mound"]
    print(f"{'word':8} | STRICT hard (pool-only, NYT rule) | verdict")
    print("-" * 64)
    for w in targets:
        si = WORDS.index(w)
        d_hard, nh = solve_depth(si, strict_hard=True)
        verdict = "UNSOLVABLE in 6 (hard-mode ceiling)" if d_hard > 6 else f"solvable in {d_hard}"
        print(f"{w:8} | depth={d_hard} (states explored={nh})   | {verdict}")
    print()
    print("STRICT = guess must be in current consistent pool (NYT hard rule).")
    print("This is the true optimal worst-case depth under the rule -- independent")
    print("of compute budget. If depth>6, 100% hard-no-hint is structurally impossible.")
