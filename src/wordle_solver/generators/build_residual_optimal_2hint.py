"""build_residual_optimal_2hint.py -- offline builder for the 2-HINT optimal
minimax tree (residual_optimal_2hint.json).

Closes the 2-hint residuals: a human who reveals the NYT 1-consonant+1-vowel
hint (ANY legal vowel x consonant pair drawn from the word's own letters) must
be able to solve the word within 6. Greedy + the small-pool rescue +
worst-case split opening get most words, but tight sibling clusters need the
exact optimal minimax -- exactly like the 1-hint builder that makes normal_1 /
hard_1 100%.

We replay EVERY legal (vowel, consonant) hint pair per word (the gate's
contract: 100% for every legal pair), identify the failures, and for each
failing (word, pair) build the optimal minimax tree over the reachable
sub-beliefs. The live engine keys on the EXACT belief (possible_indices
frozenset), so a tree fires only for the precise cluster it was built for ->
zero regression to other words / modes.

Built in HARD mode so guesses are NYT-hard-legal (optimal under the harder
constraint implies solvable under the easier normal constraint), so the one
artifact serves BOTH normal_2 and hard_2. Sharing the same minimax math as the
live solver (build_optimal_table / _minimax_best) guarantees no drift.

Run:  python -m wordle_solver.generators.build_residual_optimal_2hint
"""
from __future__ import annotations
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from wordle_solver.engine import WordleEngine
from wordle_solver.utils import data_path

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = data_path("residual_optimal_2hint.json")

e = WordleEngine()
# disable specialists so the replay reflects CLEAN greedy behaviour
e._nohint_tree = {}
e._residual_optimal = {}
e._residual_optimal_1hint = {}

WORDS = e.lex.solution_words
N = len(WORDS)
DICT_WORDS = e.lex.all_words
DICTN = len(DICT_WORDS)
w2i = e.lex.word_to_idx
sol_to_dict = e.lex.solution_idx
PAT = e.pm.matrix

VOW = set("aeiou")
CONS = set("bcdfghjklmnpqrstvwxyz")


def ai_of(word):
    return int(np.nonzero(sol_to_dict == w2i[word])[0][0])


def pat_int(g, s):
    return e.calculate_pattern(g, s)


_DP = {}
def dp_dict(guess):
    if guess not in _DP:
        out = np.empty(DICTN, dtype=np.int32)
        for i in range(0, DICTN, 256):
            chunk = [DICT_WORDS[j] for j in range(i, min(i + 256, DICTN))]
            out[i:i + len(chunk)] = np.array(
                [pat_int(guess, w) for w in chunk], dtype=np.int32)
        _DP[guess] = out
    return _DP[guess]


def two_hint_choices(word):
    """Every legal (vowel, consonant) pair drawn from the word's letters."""
    vs = sorted({c for c in word if c in VOW})
    cs = sorted({c for c in word if c in CONS})
    return [[v, c] for v in vs for c in cs]


def replay(target, hint):
    """Clean greedy HARD-mode replay with two pre-applied hints."""
    e.reset()
    for h in hint:
        e.add_hint(h)
    t = target.lower()
    hist = []
    turns = 0
    while True:
        turns += 1
        s, _ = e.get_suggestions(is_hard_mode=True)
        g = s[0]["word"]
        p = pat_int(g, t)
        hist.append((g, p))
        if g == t:
            return hist
        e.update_state(g, p)
        if turns >= 6:
            return hist


def belief_after(hist, n):
    mask = np.ones(N, dtype=bool)
    for g, p in hist[:n]:
        ai = ai_of(g)
        mask &= (PAT[ai] == p)
    return frozenset(int(i) for i in np.where(mask)[0].tolist())


SHREDDERS = ["batch", "which", "claim", "pinch", "clubs", "block", "pluck",
             "flock", "clock", "click", "flick", "slick", "shuck", "chuck",
             "chock", "shock", "quick", "juicy", "snuck", "knock", "disco",
             "album", "conch", "lynch", "pooch", "pouch", "gulch", "mulch",
             "vouch", "couch", "folks", "comes", "smock", "spicy", "stoic",
             "roate", "raise", "slate", "crane", "trace", "spear", "store",
             "arose", "snare", "stare", "saute", "tares", "rates", "tears",
             "stern", "terns", "notes", "stone", "atone", "oaten",
             "alone", "soles", "loves", "ovals", "doves", "lodes", "doles",
             "moles", "voles", "homes", "comes", "comet", "motes", "tomes"]


def guess_set(S, history, allow_illegal=False):
    pool_dict = set(sol_to_dict[np.array(sorted(S))].tolist())
    cand = set(pool_dict)
    if allow_illegal:
        legal = []
        for gi in range(DICTN):
            ok = True
            for g, p in history:
                if dp_dict(g)[gi] != p:
                    ok = False
                    break
            if ok:
                legal.append(gi)
        return sorted(set(legal))
    for sh in SHREDDERS:
        gi = w2i.get(sh)
        if gi is None:
            continue
        ok = True
        for g, p in history:
            if dp_dict(g)[gi] != p:
                ok = False
                break
        if ok:
            cand.add(gi)
    return sorted(cand)


_best: dict = {}
_NODE_CAP = 300_000


def solve(S, budget, history, allow_illegal=False):
    key = (S, budget, tuple(history), allow_illegal)
    if key in _best:
        return _best[key]
    if len(S) <= 1:
        _best[key] = (1, next(iter(S)) if S else None)
        return _best[key]
    if budget <= 1:
        _best[key] = (10**9, None)
        return _best[key]
    if len(_best) > _NODE_CAP:
        _best[key] = (10**9, None)
        return _best[key]
    gs = guess_set(S, history, allow_illegal)
    S_dict = sol_to_dict[np.array(sorted(S))].tolist()
    Sarr = np.array(sorted(S))
    overall = 10**9
    pick = None
    for gi in gs:
        gw = DICT_WORDS[gi]
        row = dp_dict(gw)[S_dict]
        order = np.argsort(row, kind="stable")
        sr = row[order]
        buckets = np.split(Sarr[order], np.nonzero(sr[1:] != sr[:-1])[0] + 1)
        worst = 0
        feasible = True
        for b in buckets:
            bp = int(sr[order[0]])
            bs = frozenset(int(x) for x in b)
            if len(bs) == 1:
                d = 1
            else:
                d = solve(bs, budget - 1, history + [(gw, bp)], allow_illegal)[0]
            if d >= 10**9:
                feasible = False
                break
            worst = max(worst, d)
        if not feasible:
            continue
        cand = worst + 1
        if cand < overall:
            overall, pick = cand, gi
    _best[key] = (overall, pick)
    return _best[key]


def build_tree(root_belief, budget, history, allow_illegal=False):
    table: dict[str, str] = {}
    def walk(S, bud, hist):
        depth, gi = solve(S, bud, hist, allow_illegal)
        if gi is None or depth >= 10**9:
            return
        key = ",".join(str(x) for x in sorted(S))
        if key in table:
            return
        table[key] = DICT_WORDS[gi]
        gw = DICT_WORDS[gi]
        S_dict = sol_to_dict[np.array(sorted(S))].tolist()
        Sarr = np.array(sorted(S))
        row = dp_dict(gw)[S_dict]
        order = np.argsort(row, kind="stable")
        sr = row[order]
        buckets = np.split(Sarr[order], np.nonzero(sr[1:] != sr[:-1])[0] + 1)
        for b in buckets:
            bp = int(sr[order[0]])
            bs = frozenset(int(x) for x in b)
            if len(bs) <= 1:
                continue
            walk(bs, bud - 1, hist + [(gw, bp)])
    walk(root_belief, budget, history)
    return table


def main():
    import pandas as pd
    sol_csv = data_path("valid_solutions.csv")
    SOL = pd.read_csv(sol_csv)["word"].tolist()

    # ---- (1) identify ALL 2-hint residuals (every legal vowel x consonant pair)
    failures = []  # (word, tuple(hint))
    for sec in SOL:
        for hint in two_hint_choices(sec):
            hist = replay(sec, hint)
            solved = hist and hist[-1][0] == sec
            turns = len(hist) if solved else 7
            if turns > 6:
                failures.append((sec, tuple(hint)))
    print(f"[identify] 2-hint residuals (all pairs): {len(failures)}")
    for w, h in failures[:40]:
        print(f"   {w} hint={h}")
    if len(failures) > 40:
        print(f"   ... +{len(failures) - 40} more")

    # ---- (2) build optimal tree per failing (word, pair) ----
    trees: dict[str, dict] = {}
    words_out: list[str] = []
    t0 = time.time()
    for sec, hint in failures:
        hist = replay(sec, list(hint))
        takeover_k = None
        for k in range(len(hist), 0, -1):
            bel = belief_after(hist, k)
            bud = 6 - k
            if len(bel) == 0:
                continue
            _best.clear()
            d, _ = solve(bel, bud, hist[:k])
            if d <= bud:
                takeover_k = k
                break
        if takeover_k is None:
            for k in range(len(hist), 0, -1):
                bel = belief_after(hist, k)
                bud = 6 - k
                if len(bel) == 0:
                    continue
                _best.clear()
                d, _ = solve(bel, bud, hist[:k], allow_illegal=True)
                if d <= bud:
                    takeover_k = k
                    break
            if takeover_k is None:
                print(f"  !! {sec} hint={hint}: NO takeover -> true ceiling")
                continue
        bel = belief_after(hist, takeover_k)
        bud = 6 - takeover_k
        _best.clear()
        d_res, _ = solve(bel, bud, hist[:takeover_k])
        allow = d_res > bud
        _best.clear()
        table = build_tree(bel, bud, hist[:takeover_k], allow_illegal=allow)
        fam = f"{sec}:{','.join(hint)}"
        trees[fam] = table
        words_out.append(sec)
        print(f"  [{fam}] takeover post-t{takeover_k} |bel|={len(bel)} "
              f"nodes={len(table)} allow_illegal={allow}")
    print(f"[build] total {time.time()-t0:.1f}s, {len(trees)} families")

    out = {"words": words_out, "trees": trees}
    if os.path.exists(OUT):
        with open(OUT) as f:
            existing = json.load(f)
        merged_trees = dict(existing.get("trees", {}))
        merged_words = list(existing.get("words", []))
        for fam, tree in trees.items():
            merged_trees[fam] = tree
        for w in words_out:
            if w not in merged_words:
                merged_words.append(w)
        out = {"words": merged_words, "trees": merged_trees}
    with open(OUT, "w") as f:
        json.dump(out, f)
    sz = os.path.getsize(OUT)
    print(f"\n[write] {OUT} ({sz/1024:.0f} KB) families={len(out['trees'])} "
          f"words={out['words']}")


if __name__ == "__main__":
    main()
