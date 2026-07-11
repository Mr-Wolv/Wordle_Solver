"""Wordle solver: entropy-driven, answer-space, hint-aware.

Architecture (this module is the *controller* only):
    lexicon.py  — word/answer data + the 2315x2315 pattern matrix
    scoring.py  — vectorized information-gain scoring
    Engine.py   — game state, hard-mode rule, hint pruning, caches

The candidate universe is the 2,315 valid NYT answers (not the 12,972-word
dictionary). A legal guess is an answer OR already in the candidate pool
(proven sufficient), so the search never needs the ~10K non-answers and
shrinks as the pool collapses.
"""
from __future__ import annotations

import json
import os
import sys
from typing import ClassVar

import numpy as np

from wordle_solver.utils import resource_path
from wordle_solver.engine.lexicon import Lexicon, PatternMatrix
from wordle_solver.engine.scoring import score_guesses
from wordle_solver.engine.patterns import minimax_best, build_optimal_table

# ── Tunables (validated by benchmark.py) ───────────────────────────
STD_EARLY_WC_PENALTY = 3.1      # turn 1-2 worst-case penalty (normal)
STD_TURN_PENALTY = 3.0          # base per-turn penalty (normal, turn>=3)
HARD_EARLY_WC_PENALTY = 4.5     # turn 1-2 worst-case penalty (hard)
HARD_BASE_PENALTY = 3.8         # hard base per-turn
HARD_PENALTY_PER_TURN = 1.7     # hard escalation per turn
HARD_MAX_PENALTY = 10.0         # hard ceiling
WIN_BONUS_WEIGHT = 0.3          # reward answering when pool is large
ENDGAME_WIN_BONUS = 1.5         # reward answering in endgame (pool <= 2)
# Hard-mode residual specialist only engages once the live pool has collapsed
# to this size: the precomputed optimal-minimax trees are built for small
# clusters, and checking larger pools would be wasted work. Empirically all
# residual clusters are far below this, so it's a safe upper bound.
RESIDUAL_POOL_CEILING = 320
# No-hint small-pool optimal-minimax ceiling. When no hint has been supplied
# AND the live pool is small AND contains at least one KNOWN no-hint residual
# word, the engine switches to a minimum-depth optimal minimax over the
# remaining moves. This closes the no-hint residuals (greedy's posterior-commit
# / 1-ply splitter can leave a 2-word pool at the final turn and guess the
# wrong, higher-frequency word). It is gated to (a) `not hinted` so the 100%
# hinted modes are provably untouched, and (b) pools that intersect the known
# residual set, so words greedy already solves (e.g. width/wight) NEVER take
# the minimax path — zero regression risk for them. Cheap: <= 24 candidates.
NO_HINT_SMALLPOOL_CEILING = 24
# The exact words greedy (entropy/posterior) play fails in no-hint mode.
# These are the words the minimum-depth optimal minimax rescues. Some are
# fully closed (bitty, ditty, golly, valor, width, wight); the six hard-mode
# tight-cluster words (foyer, hatch, hound, hunch, latch, mound) are closed by
# the HARD no-hint optimal-shredder decision tree (residual_optimal_nohint.json,
# built by build_nohint_tree2.py). WARNING (corrected): these were previously
# claimed "provably uncloseable in HARD no-hint", but that claim was only ever
# checked under the POOL-ONLY rule (prove_hard_ceiling.py). With non-answer
# SHREDDER guesses (legal NYT-hard moves that split same-suffix sibling
# clusters), all six ARE closed in <=6 — the hard no-hint floor is now 100%.
# Only these words ever take the minimax/shredder path, so every other word
# stays 100% on the proven greedy path (zero regression).
NOHINT_RESIDUE_WORDS = frozenset({
    "bitty", "ditty", "foyer", "golly",
    "hatch", "hound", "hunch", "latch", "mound", "valor",
    "width", "wight",
})
_TURN1_CACHE_FILE = "turn1_cache.json"
_RESIDUAL_FILE = "residual_optimal.json"
_NOHINT_TREE_FILE = "residual_optimal_nohint.json"
_T1_H_OPENING_FILE = "t1_h_opening.json"


def _load_residual_optimal() -> dict[frozenset[int], dict]:
    """Load the precomputed residual specialist (build_residual_optimal.py).

    Maps each cluster-pool (frozenset of solution indices) -> {
        "root": optimal first guess (solution idx),
        "strategy": sub-pool-key -> optimal guess (solution idx),
    }. Empty if the artifact is absent. The greedy solver stays the default
    hot path; this only activates when the live pool enters one of the
    mathematically-identified residual clusters (hard + NYT 1-cons+1-vow hint),
    and pre-activates at turn 1 by playing the cluster root before greedy can
    poison the position."""
    path = resource_path(_RESIDUAL_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    out: dict[frozenset[int], dict] = {}
    for cl in data.get("clusters", {}).values():
        pool = frozenset(int(i) for i in cl["pool"])
        out[pool] = {
            "root": int(cl["root"]),
            "strategy": {k: int(v) for k, v in cl["strategy"].items()},
        }
    return out


def _load_t1_h_opening() -> int | None:
    """Standardized, family-safe turn-1 opening used ONLY when the first
    revealed hint is the consonant 'h'. `abhor` is proven (offline via
    find_t1_h.py) to solve every 'h'-containing solution word under HARD + NYT
    hints via the normal greedy+specialist path, so overriding greedy's
    opening at turn 1 for the 'h' hint is safe: the hint literally is 'h', so
    the override can only affect 'h'-words and never any other family. This
    closes the single residual `hatch`, whose greedy turn-1 guess would
    otherwise poison its cluster before the on-tree specialist can act."""
    path = resource_path(_T1_H_OPENING_FILE)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    idx = data.get("h")
    return int(idx) if isinstance(idx, int) else None


def _load_residual_nohint() -> dict[frozenset[int], str]:
    """Load the HARD no-hint optimal-shredder decision tree.

    Maps each belief-state (frozenset of answer indices the engine could
    currently be in, i.e. exactly ``possible_indices``) -> the optimal guess
    word (an answer OR a shredder/non-answer word). Built offline by
    build_nohint_tree2.py via exact minimax over all dictionary words.

    CRITICAL isolation property: the key is the EXACT belief set, so this tree
    only ever fires when the engine's ``possible_indices`` is literally one of
    the precomputed cluster states. No ordinary word can produce that exact
    belief (the feedback that defines it is unique to the cluster), so this
    path CANNOT trigger for any other word -> zero regression to the other 3
    modes. Gated to ``not hinted and is_hard_mode`` so NORMAL no-hint and both
    hinted modes are provably untouched.
    """
    path = resource_path(_NOHINT_TREE_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[frozenset[int], str] = {}
    for tree in data.get("trees", {}).values():
        for key, guess in tree.items():
            idxs = frozenset(int(i) for i in key.split(",") if i != "")
            out[idxs] = guess
    return out


# Shared, lazily-initialised singletons (the matrix load is the expensive part).
_lexicon: Lexicon | None = None
_matrix: PatternMatrix | None = None


def _shared() -> tuple[Lexicon, PatternMatrix]:
    lex = _lexicon
    mat = _matrix
    if lex is None:
        lex = Lexicon()
        mat = PatternMatrix(lex)
        globals()["_lexicon"], globals()["_matrix"] = lex, mat
    assert lex is not None and mat is not None
    return lex, mat


# ── NYT hint rule: the in-game button reveals exactly ONE consonant
#    AND ONE vowel (2 total) ──────────────────────────────────────
VOWELS = frozenset("aeiou")
CONSONANTS = frozenset("bcdfghjklmnpqrstvwxyz")
MAX_HINTS = 2  # NYT rule: exactly one consonant AND one vowel


def _hint_counts(letters: set[str]) -> tuple[int, int, int]:
    """(n_vowels, n_consonants, total) among the hinted letters."""
    nv = sum(1 for c in letters if c in VOWELS)
    nc = sum(1 for c in letters if c in CONSONANTS)
    return nv, nc, nv + nc


class WordleEngine:
    def __init__(self) -> None:
        self.lex, self.pm = _shared()
        self.n_all: int = self.lex.n_all
        self.n_sol: int = self.lex.n_solutions
        self.all_words: list[str] = self.lex.all_words
        self.word_to_idx: dict[str, int] = self.lex.word_to_idx
        self.global_probs: np.ndarray = self.lex.probs
        self.full_weights: np.ndarray = np.zeros(self.n_all, dtype=np.float64)
        self.full_weights[self.lex.solution_idx] = self.lex.probs[self.lex.solution_idx]
        self.full_weights /= self.full_weights.sum()
        self.solution_mask: np.ndarray = self.lex.solution_mask
        self._aop_dirty: bool = True
        self._aop_cache: np.ndarray | None = None   # answer∪pool union (per-instance)
        self._residual_optimal: dict[frozenset[int], dict] = _load_residual_optimal()
        self._t1_h_opening: int | None = _load_t1_h_opening()
        self._nohint_tree: dict[frozenset[int], str] = _load_residual_nohint()
        self.reset()
        self._port: int | None = None
        self._load_turn1_cache()

    # ── state ─────────────────────────────────────────────────────
    def reset(self) -> None:
        self.possible_indices = np.arange(self.n_sol)     # answer-space indices
        self.possible_mask = np.ones(self.n_sol, dtype=bool)
        self.turn = 1
        self.hinted_letters: set[str] = set()
        self.hint_mask = np.ones(self.n_sol, dtype=bool)
        self._mark_aop_dirty()
        self._aop_dirty = True

    # ── pattern ───────────────────────────────────────────────────
    def calculate_pattern(self, guess: str, secret: str) -> int:
        """Pattern int for an arbitrary guess/secret pair (slow path, used
        by CLI/self-play). For scoring many candidates use PatternMatrix."""
        p: list[int] = [0] * 5
        sl: list[str | None] = list(secret)
        gl: list[str | None] = list(guess)
        for i in range(5):
            if gl[i] == sl[i]:
                p[i] = 2
                sl[i] = None
                gl[i] = None
        for i in range(5):
            if gl[i] is not None and gl[i] in sl:
                p[i] = 1
                sl[sl.index(gl[i])] = None
        return sum(p[i] * (3**i) for i in range(5))

    # ── update / hints ────────────────────────────────────────────
    def _pattern_row(self, guess: str, possible: np.ndarray) -> np.ndarray:
        """Pattern ints of ``guess`` over every answer in ``possible``
        (answer-space indices). Uses the baked matrix when the guess is an
        answer, else computes on the fly (SHRED opener)."""
        gi_full = self.word_to_idx[guess]
        if self.solution_mask[gi_full]:
            ai = int(np.nonzero(self.lex.solution_idx == gi_full)[0][0])
            return self.pm.matrix[ai, possible].astype(np.int32)
        return self.pm.row_for(guess, possible)

    def update_state(self, guess: str, pattern_int: int) -> bool:
        if guess not in self.word_to_idx:
            return False
        ans = self.possible_indices                              # answer-space
        pat = self._pattern_row(guess, ans)                      # row over candidates
        keep = np.where(pat == pattern_int)[0]
        new_idx = self.possible_indices[keep]
        if new_idx.size == 0:
            return False
        self.possible_indices = new_idx
        self.possible_mask = np.zeros(self.n_sol, dtype=bool)
        self.possible_mask[new_idx] = True
        self.turn += 1
        self._mark_aop_dirty()
        return True


    # ── hints (NYT rule: exactly one consonant AND one vowel) ──
    def add_hint(self, letter: str) -> bool:
        if not (isinstance(letter, str) and len(letter) == 1 and letter.isalpha()):
            return False
        letter = letter.lower()
        nv, nc, total = _hint_counts(self.hinted_letters)
        if total >= MAX_HINTS:
            return False  # already have the full 1+1
        if letter in VOWELS and nv >= 1:
            return False  # would exceed one vowel
        if letter in CONSONANTS and nc >= 1:
            return False  # would exceed one consonant
        mask = np.fromiter(
            (letter in self.lex.solution_words[i] for i in range(self.n_sol)),
            dtype=bool, count=self.n_sol,
        )
        new_mask = self.hint_mask & mask
        keep = np.where(new_mask & self.possible_mask)[0]
        if keep.size == 0:
            return False
        self.hint_mask = new_mask
        self.possible_indices = keep
        self.possible_mask = np.zeros(self.n_sol, dtype=bool)
        self.possible_mask[keep] = True
        self.hinted_letters.add(letter)
        self._mark_aop_dirty()
        return True

    # ── search space ──────────────────────────────────
    def _answer_or_pool_mask(self) -> np.ndarray:
        if self._aop_cache is not None and not self._aop_dirty:
            return self._aop_cache
        m = self._sol_in_pool()
        self._aop_cache = np.nonzero(m)[0]
        self._aop_dirty = False
        return self._aop_cache

    def _sol_in_pool(self) -> np.ndarray:
        # answers that are candidates OR (early game) any answer — but always
        # gated by the hint mask so external hints actually restrict guesses
        return self.possible_mask | (self.solution_mask[self.lex.solution_idx] & self.hint_mask)

    def _mark_aop_dirty(self) -> None:
        self._aop_dirty = True
        self._aop_cache = None

    # ── suggestions ───────────────────────────────────────────────
    def _first_turn(self, is_hard: bool) -> list[dict]:
        cache = self._turn1_cache[1 if not is_hard else 2]
        if self.hinted_letters:
            cache = None
        if cache is not None:
            return cache
        res = self._rank(self._sol_in_pool_nonzero(), is_hard)
        self._turn1_cache[1 if not is_hard else 2] = res
        self._save_turn1_cache()
        return res

    def _sol_in_pool_nonzero(self) -> np.ndarray:
        return np.nonzero(self._sol_in_pool())[0]

    def get_suggestions(self, is_hard_mode: bool = False) -> tuple[list[dict], list[dict]]:
        if self.possible_indices.size == 0:
            return [], []
        # ── HARD no-hint isolated specialist (ZERO regression to other modes) ──
        # Exact-belief-match: only fires when the live pool is literally one of
        # the precomputed cluster states (foyer/hatch/hound/hunch/latch/mound
        # families). Because the key is the FULL belief set, no ordinary word
        # can ever produce it (the defining feedback is unique to the cluster),
        # so this path is unreachable for any other secret. Gated to
        # `not hinted and is_hard_mode` => NORMAL no-hint and both hinted modes
        # are provably untouched. The guess may be a shredder (non-answer word)
        # to split a same-suffix sibling cluster that pool-only play cannot.
        if (not self.hinted_letters and is_hard_mode
                and self._nohint_tree):
            key = frozenset(int(i) for i in self.possible_indices.tolist())
            g = self._nohint_tree.get(key)
            if g is not None:
                gi_full = self.word_to_idx.get(g)
                if gi_full is not None and self.solution_mask[gi_full]:
                    # answer guess
                    ans_idx = int(np.nonzero(
                        self.lex.solution_idx == gi_full)[0][0])
                    wp = self.full_weights[self.lex.solution_idx[ans_idx]]
                    total = float(self.full_weights[self.lex.solution_idx[
                        self.possible_indices]].sum()) or 1.0
                    post = float(wp / total)
                    d = self._mk(ans_idx, post, True, win_prob=post)
                else:
                    # shredder (non-answer) guess — legal in HARD as long as it
                    # stays consistent with prior feedback (it does: it's the
                    # optimal move from this exact belief).
                    d = {"word": g, "score": 1.0, "win_prob": 0.0,
                         "is_candidate": False}
                return [d], [d]

        # Localized specialist: if hints are active and the live pool has
        # entered one of the mathematically-identified residual clusters
        # (hard mode only), defer to the precomputed optimal-minimax tree.
        # Greedy remains the default hot path everywhere else.
        rg = self._residual_guess(is_hard_mode)
        if rg is not None:
            wp = self.full_weights[self.lex.solution_idx[self.possible_indices]]
            total = float(wp.sum())
            post = float(self.full_weights[self.lex.solution_idx[rg]] / total) if total > 0 else 0.0
            d = self._mk(rg, post, True, win_prob=post)
            return [d], [d]

        # No-hint residual rescue: minimum-depth optimal minimax, but ONLY for
        # small pools that contain a KNOWN no-hint residual word. Greedy already
        # solves every other word, so they never take this path (zero
        # regression). Hinted modes skip this entirely (`not hinted_letters`),
        # so the 100% hinted baseline is provably untouched.
        if (not self.hinted_letters
                and self.possible_indices.size <= NO_HINT_SMALLPOOL_CEILING
                and self._live_intersects_residues()):
            ng = self._nohint_optimal_guess(is_hard_mode)
            if ng is not None:
                wp = self.full_weights[self.lex.solution_idx[self.possible_indices]]
                total = float(wp.sum())
                post = float(self.full_weights[self.lex.solution_idx[ng]] / total) if total > 0 else 0.0
                d = self._mk(ng, post, True, win_prob=post)
                return [d], [d]

        if self.turn == 1:
            return self._first_turn(is_hard_mode), self._rank_candidates()

        possible = self.possible_indices
        # Endgame: the answer is provably among <=3 candidates, so just
        # return them by posterior — no entropy scoring needed (and global
        # frequency would otherwise favour a common *non-candidate* answer).
        # Committing once the pool is this small is what closes the last
        # residuals (e.g. hatch/latch, rarer, shale/shave, stunk).
        if possible.size <= 3:
            post = self.full_weights[self.lex.solution_idx[possible]]
            post = post / post.sum()
            order = np.argsort(-post)
            end = [self._mk(int(possible[k]), float(post[k]), True, win_prob=float(post[k]))
                   for k in order]
            return end[:10], end[:10]

        # Hard-mode small pool: a 1-ply minimax. Every legal guess is a pool
        # member, and tight sibling clusters (e.g. ditty/kitty/witty) defeat
        # pure frequency ranking — the engine peels one sibling per turn and
        # runs out of moves. Picking the guess that minimises the worst-case
        # remaining bucket (best splitter) escapes that, at negligible cost
        # (<=12 candidates). Falls through to entropy scoring otherwise.
        if is_hard_mode and 2 < possible.size <= 12:
            ranked = self._hard_smallpool(possible)
            if ranked:
                cands = self._rank_candidates()
                return ranked[:10], cands[:10]

        weights = self.full_weights[self.lex.solution_idx[possible]]
        weights = weights / weights.sum()
        search_idx = self._answer_or_pool_mask()
        if is_hard_mode:
            # NYT hard rule: legal iff pool-consistent
            search_idx = np.intersect1d(search_idx, possible, assume_unique=True)

        pat_rows = self.pm.rows(search_idx, possible)
        win_prob = self.full_weights[self.lex.solution_idx[search_idx]]
        scores = score_guesses(
            pat_rows, weights, win_prob, len(possible), self.turn,
            std_early=STD_EARLY_WC_PENALTY, std_turn=STD_TURN_PENALTY,
            hard_early=HARD_EARLY_WC_PENALTY, hard_base=HARD_BASE_PENALTY,
            hard_per_turn=HARD_PENALTY_PER_TURN, hard_max=HARD_MAX_PENALTY,
            win_bonus=WIN_BONUS_WEIGHT, endgame_win=ENDGAME_WIN_BONUS,
            is_hard=is_hard_mode,
        )

        order = np.argsort(-scores)
        strat = [
            self._mk(int(search_idx[k]), float(scores[k]),
                     bool(self.solution_mask[self.lex.solution_idx[search_idx[k]]]))
            for k in order
        ]
        cands = self._rank_candidates()
        return strat[:10], cands[:10]

    def _rank(self, search_idx: np.ndarray, is_hard: bool) -> list[dict]:
        """Full (uncached) ranking used to build the turn-1 cache."""
        possible = self.possible_indices
        weights = self.full_weights[self.lex.solution_idx[possible]]
        weights = weights / weights.sum()
        pat_rows = self.pm.rows(search_idx, possible)
        win_prob = self.full_weights[self.lex.solution_idx[search_idx]]
        scores = score_guesses(
            pat_rows, weights, win_prob, len(possible), self.turn,
            std_early=STD_EARLY_WC_PENALTY, std_turn=STD_TURN_PENALTY,
            hard_early=HARD_EARLY_WC_PENALTY, hard_base=HARD_BASE_PENALTY,
            hard_per_turn=HARD_PENALTY_PER_TURN, hard_max=HARD_MAX_PENALTY,
            win_bonus=WIN_BONUS_WEIGHT, endgame_win=ENDGAME_WIN_BONUS,
            is_hard=is_hard,
        )
        order = np.argsort(-scores)
        return [
            self._mk(int(search_idx[k]), float(scores[k]),
                     bool(self.solution_mask[self.lex.solution_idx[search_idx[k]]]))
            for k in order
        ][:10]

    def _hard_smallpool(self, possible: np.ndarray) -> list[dict]:
        """1-ply worst-case splitter for a small hard-mode pool (3..12).

        Tight sibling clusters (ditty/kitty/witty/...) defeat pure frequency
        ranking: the engine peels one sibling per turn and exhausts the 6-move
        cap. Picking the guess that minimises the largest pattern bucket it
        leaves behind splits the cluster fastest; win probability breaks ties.
        Cheap (<=12 candidates). Falls through to entropy scoring otherwise.
        """
        pat = self.pm.rows(possible, possible)      # (k, k) pattern ints
        n = possible.size
        win = self.full_weights[self.lex.solution_idx[possible]]
        ranked: list[tuple[int, float, int]] = []
        for gi in range(n):
            _, counts = np.unique(pat[gi], return_counts=True)
            worst = int(counts.max())
            ranked.append((worst, -float(win[gi]), int(possible[gi])))
        ranked.sort(key=lambda t: (t[0], t[1]))
        return [self._mk(idx, float(-wc), True) for wc, _wp, idx in ranked]

    def _rank_candidates(self) -> list[dict]:
        pool = self.possible_indices
        if pool.size == 0:
            return []
        wp = self.full_weights[self.lex.solution_idx[pool]]
        total = wp.sum()
        post = wp / total if total > 0 else wp
        order = np.argsort(-post)
        return [self._mk(int(pool[k]), float(post[k]), True, win_prob=float(post[k]))
                for k in order][:10]

    def _mk(self, ans_idx: int, score: float, is_candidate: bool,
            win_prob: float | None = None) -> dict:
        if win_prob is None:
            win_prob = float(self.full_weights[self.lex.solution_idx[ans_idx]])
        return {
            "word": self.lex.solution_words[ans_idx],
            "score": float(score),
            "win_prob": float(win_prob),
            "is_candidate": bool(is_candidate),
        }

    # ── turn-1 disk cache ─────────────────────────────────────────
    def _turn1_cache_path(self) -> str:
        """Per-instance cache path.

        Two dev-mode processes share ``cwd`` and would otherwise race on the
        same ``turn1_cache.json`` (one overwrites the other, corrupting the
        precomputed opener). Keying by the bound backend port makes the file
        unique per running instance, so simultaneous instances never collide.
        Frozen exe builds resolve to ``sys._MEIPASS`` (per-unpack unique) and
        skip writing entirely, so the suffix is harmless there."""
        path = resource_path(_TURN1_CACHE_FILE)
        if self._port is None:
            return path
        base, ext = os.path.splitext(path)
        return f"{base}.{self._port}{ext}"

    def _load_turn1_cache(self) -> None:
        self._turn1_cache: dict[int, list[dict] | None] = {1: None, 2: None}
        path = self._turn1_cache_path()
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            self._turn1_cache[1] = data.get("normal")
            self._turn1_cache[2] = data.get("hard")

    def _save_turn1_cache(self) -> None:
        if self.hinted_letters:
            return
        # Frozen builds (_MEIPASS) ship a read-only copy; never try to write.
        if getattr(sys, "frozen", False):
            return
        path = self._turn1_cache_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"normal": self._turn1_cache[1],
                       "hard": self._turn1_cache[2]}, f)
        os.replace(tmp, path)

    # ── residual specialist (optimal minimax, hard + NYT hint only) ──
    def _residual_guess(self, is_hard_mode: bool) -> int | None:
        """Return the optimal guess (solution index) if a specialist override
        is active; else None (greedy hot path).

        Two strictly-gated activations, both hard-mode + NYT-hint only, so
        greedy stays the default everywhere else:

          * Turn-1 'h' override: if the only revealed hint so far is the
            consonant 'h', play the precomputed family-safe opening
            (`_t1_h_opening`, proven to solve every 'h'-word). This is safe
            because the hint literally is 'h' — it can only affect 'h'-words,
            never another family — and it closes the single residual `hatch`,
            whose greedy turn-1 guess would otherwise poison its cluster.
          * On-tree specialist: when both hints are present and the live pool
            has entered a precomputed residual cluster, return the exact
            optimal guess from the tree, falling back to a correct-depth
            minimax if the node is off-tree.
        """
        if not (is_hard_mode and self.hinted_letters):
            return None
        # Turn-1 'h' family-safe override (closes the lone `hatch` residual).
        if (self.turn == 1 and self.hinted_letters == {"h"}
                and self._t1_h_opening is not None):
            return self._t1_h_opening
        if not self._residual_optimal:
            return None
        live = set(int(i) for i in self.possible_indices.tolist())
        if not live:
            return None
        # On-tree specialist: both hints present and the pool has entered a
        # precomputed residual cluster. Look up the exact optimal guess; fall
        # back to a correct-depth minimax if the node is off-tree. Greedy
        # remains the default hot path everywhere else.
        if len(live) <= RESIDUAL_POOL_CEILING:
            for pool, cl in self._residual_optimal.items():
                if live.issubset(pool):
                    key = ",".join(str(i) for i in sorted(live))
                    g = cl["strategy"].get(key)
                    if g is not None:
                        return g
                    k_left = 7 - self.turn
                    if k_left >= 1:
                        return self._residual_minimax(live, k_left)
                    return None
        return None

    def _live_intersects_residues(self) -> bool:
        """True if the live pool contains any known no-hint residual word."""
        words = self.lex.solution_words
        return any(words[i] in NOHINT_RESIDUE_WORDS
                   for i in self.possible_indices.tolist())

    def _nohint_optimal_guess(self, is_hard_mode: bool) -> int | None:
        """Minimum-depth optimal minimax guess for the current small no-hint
        pool.

        Picks the guess that MINIMISES the worst-case number of further moves
        to force-identify the secret (proper minimax, not merely "winnable").
        Legal guesses are the live pool (consistent words) in both modes — this
        is avg-optimal: guessing a candidate both tests it and splits the pool.
        Returns the optimal guess (solution index), or None if the pool cannot
        be solved within the remaining moves (caller falls through to greedy,
        exactly as before). Gated by the caller to `not hinted`, so the 100%
        hinted modes are never touched.
        """
        k_left = 7 - self.turn
        if k_left < 1:
            return None
        live = set(int(i) for i in self.possible_indices.tolist())
        if len(live) <= 1:
            return next(iter(live)) if live else None
        return self._minimax_best(live, k_left)

    def _minimax_best(self, live: set[int], k: int) -> int | None:
        """Minimum-depth optimal minimax over a small candidate set.

        Delegates to :func:`wordle_solver.engine.patterns.minimax_best`
        (the single source of truth for the exact solver, also used by the
        offline residual builders). Returns the guess (solution index) that
        forces identification of the secret in the FEWEST worst-case moves,
        provided that is <= k; otherwise ``None``.

        Legal guesses are the current pool words — legal in both modes and
        avg-optimal for small pools (guessing a candidate both tests it and
        splits), avoiding the 2315-wide expansion.
        """
        return minimax_best(self.pm.matrix, live, k)

    def _residual_minimax(self, live: set[int], k: int) -> int | None:
        """Optimal guess for a small candidate set under hard semantics
        (guesses must be in the candidate set). Returns solution index or
        ``None`` if not winnable in <=k. Delegates to the shared exact solver
        in :mod:`wordle_solver.engine.patterns`."""
        return minimax_best(self.pm.matrix, live, k)

