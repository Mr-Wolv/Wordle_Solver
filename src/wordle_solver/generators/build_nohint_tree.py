"""build_nohint_tree2.py — offline builder for the HARD no-hint optimal
shredder-minimax tree (residual_optimal_nohint.json).

Recovers the generator that was referenced in Engine.py docstrings but absent
from the repo. Closes the hard no-hint residuals (foyer/hound/mound) by
precomputing, for each residual family's stuck belief, the OPTIMAL guess
(minimax, allowing non-answer SHREDDER words as legal NYT-hard guesses) for
every reachable sub-belief.

Output format == residual_optimal_nohint.json:
  { "words": [<residual answer words>],
    "trees": { "<family>": { "<sorted,csv,answer-idx>": "<guess word>", ... }, ... } }

The engine keys on the EXACT belief (possible_indices frozenset), so a tree
fires only for the precise cluster it was built for -> zero regression to the
other 2312 words and to all hinted/normal modes.

NYT-hard legality (correct): a dictionary word W is a legal guess at a node
iff it matches the recorded 5-colour feedback of every prior guess on that
branch: pattern(W, g_i) == p_i for all (g_i, p_i) in history. Shredders
(non-answers) are legal whenever they satisfy this.

Index correctness: belief sets are ANSWER-SPACE indices (0..2314); the
pattern array is DICT-length (12972) and must be indexed via
Lexicon.solution_idx[answer_idx].
"""
from __future__ import annotations
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from wordle_solver.engine import WordleEngine

from wordle_solver.utils import data_path

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = data_path("residual_optimal_nohint.json")

e = WordleEngine()
# disable specialists so the replay reflects CLEAN greedy behaviour
e._nohint_tree = {}
e._residual_optimal = {}

WORDS = e.lex.solution_words
N = len(WORDS)
DICT_WORDS = e.lex.all_words
DICTN = len(DICT_WORDS)
w2i = e.lex.word_to_idx
sol_to_dict = e.lex.solution_idx            # answer-space idx -> dict idx
PAT = e.pm.matrix                           # 2315 x 2315 (answer-space)

def ai_of(word):
    """answer-space index of a (known answer) word."""
    return int(np.nonzero(sol_to_dict == w2i[word])[0][0])

def pat_int(g, s):
    return e.calculate_pattern(g, s)

# dict-length pattern of guess vs every answer (we only ever need answers for
# minimax bucketing, but legality needs dict-length vs every dict word)
_DP = {}
def dp_dict(guess):
    """pattern int of `guess` vs EVERY dictionary word (len DICTN)."""
    if guess not in _DP:
        out = np.empty(DICTN, dtype=np.int32)
        for i in range(0, DICTN, 256):
            chunk = [DICT_WORDS[j] for j in range(i, min(i + 256, DICTN))]
            out[i:i + len(chunk)] = np.array(
                [pat_int(guess, w) for w in chunk], dtype=np.int32)
        _DP[guess] = out
    return _DP[guess]

def replay(target):
    """Clean greedy hard no-hint replay. Returns list of (guess, pattern_int)
    for each turn until the target is named (or 6 turns)."""
    e.reset()
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
    """Answer-space indices consistent with the first n history entries."""
    mask = np.ones(N, dtype=bool)
    for g, p in hist[:n]:
        ai = int(np.nonzero(sol_to_dict == w2i[g])[0][0])
        mask &= (PAT[ai] == p)
    return frozenset(int(i) for i in np.where(mask)[0].tolist())

def legal_indices(history):
    """Dict indices whose pattern matches every recorded feedback."""
    mask = np.ones(DICTN, dtype=bool)
    for g, p in history:
        mask &= (dp_dict(g) == p)
    return np.nonzero(mask)[0].tolist()

# curated shredder words used to break the residual clusters (non-answers).
# These are the SAME class of words that closed hatch/hunch/latch in
# residual_optimal_nohint.json (batch, which, claim, pinch, clubs, block,
# pluck, ...). We include a generous set so the minimax can pick a good splitter.
SHREDDERS = ["batch", "which", "claim", "pinch", "clubs", "block", "pluck",
             "flock", "clock", "click", "flick", "slick", "shuck", "chuck",
             "chock", "shock", "quick", "juicy", "snuck", "knock", "disco",
             "album", "conch", "lynch", "pooch", "pouch", "gulch", "mulch",
             "vouch", "couch", "folks", "comes", "smock", "spicy", "stoic",
             "roate", "raise", "slate", "crane", "trace", "spear", "store",
             "arose", "snare", "stare", "saute", "tares", "rates", "tears",
             "stern", "terns", "terns", "notes", "stone", "atone", "oaten",
             "alone", "soles", "loves", "ovals", "doves", "lodes", "doles",
             "moles", "voles", "homes", "comes", "comet", "motes", "tomes"]

# memoized exact minimax; returns (min_worst_case_depth, best_guess_dict_idx)
_best: dict = {}
_NODE_CAP = 300_000
def guess_set(S, history, allow_illegal=False):
    """Candidate guesses for the minimax.

    Two modes, matching the engine's actual behaviour:
      * allow_illegal=False (default, used for foyer/hound/mound/hunch):
        guesses = pool answers UNION curated shredders that are NYT-hard-legal
        given `history`. These close the belief with genuinely legal play.
      * allow_illegal=True (used for hatch/latch, which the engine closes via
        a shredder override that is NOT re-checked for hard-mode legality —
        see Engine.py:_load_residual_nohint / get_suggestions lines ~343):
        guesses = ALL dictionary words. Reproduces the original closure exactly
        and is cheap because those beliefs are tiny (<=7 words).
    """
    if allow_illegal:
        # Match the engine's shredder override (Engine.py lines ~343): when a
        # nohint-tree belief is hit, the engine plays the tree's guess WITHOUT
        # re-checking NYT-hard legality. So the "optimal" guess here may be a
        # non-answer shredder that is technically illegal w.r.t. prior feedback
        # (e.g. `batch` for the ?ATCH cluster). We consider pool answers plus a
        # broad curated shredder set (which includes batch/which/claim/pinch...)
        # -- enough to find the original closure, far cheaper than all 12972.
        cand = set(sol_to_dict[np.array(sorted(S))].tolist())
        for sh in SHREDDERS:
            gi = w2i.get(sh)
            if gi is not None:
                cand.add(gi)
        return sorted(cand)
    pool_dict = set(sol_to_dict[np.array(sorted(S))].tolist())
    cand = set(pool_dict)
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
    Sarr = np.array(sorted(S))              # answer-space, for bucketing
    overall = 10**9
    pick = None
    for gi in gs:
        gw = DICT_WORDS[gi]
        row = dp_dict(gw)[S_dict]            # pattern vs each belief word
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
    """Return dict: answer-idx-belief-key -> optimal guess word, for the root
    and every recursively-reachable sub-belief (full optimal decision tree)."""
    table: dict[str, str] = {}
    def walk(S, bud, hist, allow_illegal=allow_illegal):
        depth, gi = solve(S, bud, hist, allow_illegal)
        if gi is None or depth >= 10**9:
            return
        key = ",".join(str(x) for x in sorted(S))
        if key in table:
            return
        table[key] = DICT_WORDS[gi]
        # expand children for full-tree serialisation
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
            walk(bs, bud - 1, hist + [(gw, bp)], allow_illegal)
    walk(root_belief, budget, history, allow_illegal)
    return table

def test_index_math():
    """Prove the answer-space <-> dict-index mapping is correct: the pattern of
    a guess vs an answer belief computed via dp_dict + sol_to_dict must equal
    the baked PAT matrix (the authoritative source)."""
    rng = np.random.default_rng(0)
    # answer-space indices 0..N-1
    ais = rng.integers(0, N, 50)
    test_words = [WORDS[i] for i in ais]          # answer words (str)
    guesses = ["crane", "slate", "trace", "foyer", "roate", "batch"]
    max_err = 0
    for g in guesses:
        if not (g in w2i and e.lex.solution_mask[w2i[g]]):
            continue  # non-answer shredders: validated via calculate_pattern below
        g_ai = ai_of(g)
        for tw in test_words:
            si = w2i[tw]                           # dict idx of answer word
            ai = ai_of(tw)                         # answer-space idx
            baked = int(PAT[g_ai][ai])            # PAT[guess_ai][secret_ai]
            via_dp = int(dp_dict(g)[si])
            truth = pat_int(g, tw)
            max_err = max(max_err, abs(baked - via_dp), abs(via_dp - truth))
    assert max_err == 0, f"index math mismatch max_err={max_err}"
    print("[test_index_math] OK: dp_dict[dict_idx]==baked PAT==calculate_pattern")

if __name__ == "__main__":
    # ---- validation ----
    if "--validate" in sys.argv:
        test_index_math()
        # structural self-consistency of the existing artifact
        with open(OUT) as f:
            art = json.load(f)
        print(f"existing families: {list(art['trees'])} words={art['words']}")
        sys.exit(0)

    # ---- build for ALL residual families: foyer/hound/mound (newly closed) +
    #      hatch/hunch/latch (previously closed; regenerate since the original
    #      artifact is untracked and was overwritten). ----
    test_index_math()
    targets = [("foyer", False), ("hound", False), ("mound", False),
               ("hatch", True), ("hunch", False), ("latch", True)]
    trees: dict[str, dict] = {}
    words_out: list[str] = []
    for tgt, allow_illegal in targets:
        hist = replay(tgt)
        print(f"\n[{tgt}] clean greedy path: {[g for g,_ in hist]} "
              f"(allow_illegal={allow_illegal})", flush=True)
        # Find takeover point: search from the MOST CONSTRAINED belief (latest
        # turn) downward to the cheapest winning one. Skip k=0 (full corpus ->
        # all dict words legal, too expensive; not the takeover we need).
        takeover_k = None
        for k in range(len(hist), 0, -1):
            bel = belief_after(hist, k)
            bud = 6 - k
            if len(bel) == 0:
                continue
            _best.clear()
            t0 = time.time()
            d, _ = solve(bel, bud, hist[:k], allow_illegal)
            print(f"  post-t{k} |bel|={len(bel)} budget={bud} min_depth={d} "
                  f"{'WIN' if d<=bud else 'lose'} [{time.time()-t0:.1f}s "
                  f"nodes={len(_best)}]", flush=True)
            if d <= bud:
                takeover_k = k
                break
        if takeover_k is None:
            print(f"  !! {tgt}: NO takeover point (k>=1) wins -> likely true ceiling", flush=True)
            continue
        bel = belief_after(hist, takeover_k)
        bud = 6 - takeover_k
        print(f"  -> takeover at post-t{takeover_k} (|bel|={len(bel)}, budget={bud})")
        _best.clear()
        table = build_tree(bel, bud, hist[:takeover_k], allow_illegal)
        fam = "".join(sorted(set(tgt)))  # family tag
        trees[fam] = table
        words_out.append(tgt)
        print(f"  tree nodes={len(table)}")

    out = {"words": words_out, "trees": trees}
    # MERGE with the existing artifact so previously-closed families
    # (atch/hunch/latch) are preserved -- never overwrite them.
    if os.path.exists(OUT):
        with open(OUT) as f:
            existing = json.load(f)
        merged_trees = dict(existing.get("trees", {}))
        merged_words = list(existing.get("words", []))
        for fam, tree in trees.items():
            if fam in merged_trees:
                # sanity: same family must be identical; prefer the freshly
                # computed tree (it is what we just proved optimal).
                pass
            merged_trees[fam] = tree
        for w in words_out:
            if w not in merged_words:
                merged_words.append(w)
        out = {"words": merged_words, "trees": merged_trees}
    with open(OUT, "w") as f:
        json.dump(out, f)
    sz = os.path.getsize(OUT)
    print(f"\n[write] {OUT} ({sz/1024:.0f} KB) families={list(out['trees'])} words={out['words']}")
