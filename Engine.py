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

from utils import resource_path
from lexicon import Lexicon, PatternMatrix
from scoring import score_guesses

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
_TURN1_CACHE_FILE = "turn1_cache.json"
_RESIDUAL_FILE = "residual_optimal.json"
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

    def _residual_minimax(self, live: set[int], k: int) -> int | None:
        """Optimal guess for a small candidate set under hard semantics
        (guesses must be in the candidate set). Returns solution index or
        None if not winnable in <=k. Live set is solution indices."""
        M = self.pm.matrix
        live_frozen = frozenset(live)

        def solve(S: frozenset[int], depth: int) -> int | None:
            if len(S) == 1:
                return next(iter(S))
            if depth <= 1:
                return None
            for g in S:
                ok = True
                row = M[g]
                parts: dict[int, set[int]] = {}
                for t in S:
                    p = int(row[t])
                    b = parts.get(p)
                    if b is None:
                        parts[p] = {t}
                    else:
                        b.add(t)
                for v in parts.values():
                    if solve(frozenset(v), depth - 1) is None:
                        ok = False
                        break
                if ok:
                    return g
            return None

        return solve(live_frozen, k)
