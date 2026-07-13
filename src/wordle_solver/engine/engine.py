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
from typing import ClassVar

import numpy as np

from wordle_solver.utils import resource_path
from wordle_solver.engine.lexicon import Lexicon, PatternMatrix
from wordle_solver.engine.scoring import score_guesses
from wordle_solver.engine.patterns import (
    minimax_best, build_optimal_table, calculate_pattern,
)
from wordle_solver.engine.modes import ModeSpec, MODE_REGISTRY

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
# 2-HINT residual words: secrets whose (vowel x consonant) hint pool is tight
# enough that greedy alone can strand them. The 2-hint specialist tree
# (residual_optimal_2hint.json) plus the bounded minimax fallback close these.
# Gating the fallback behind this set keeps the gate fast (the minimax only
# runs for words that can actually need it).
HINT2_RESIDUE_WORDS = frozenset({
    "chard", "graze", "hound", "shale", "shave", "sower", "vaunt",
    # hard_2 residuals surfaced by the exhaustive gate (the 2-hint specialist
    # tree + greedy strand these in hard mode even though normal_2 solves them):
    "baste", "boxer", "cower", "dilly", "foyer", "glade", "goner",
    "hatch", "homer", "latch", "mound",
    "sight", "stash", "taffy", "tight", "wight", "wound",
})

_RESIDUAL_FILE = "residual_optimal.json"
_NOHINT_TREE_FILE = "residual_optimal_nohint.json"
_T1_H_OPENING_FILE = "t1_h_opening.json"
_RESIDUAL_1HINT_FILE = "residual_optimal_1hint.json"


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


def _load_residual_optimal_1hint() -> dict[frozenset[int], str]:
    """Load the 1-HINT optimal-minimax decision tree (build_residual_optimal_1hint.py).

    Maps each belief-state (frozenset of answer indices) -> the optimal guess
    word, for the six normal single-hint residuals that clean greedy cannot
    close. Keyed on the EXACT belief, so it only fires for those precise
    cluster states -> zero regression to other words and to no-hint / 2-hint /
    hard modes. Gated to single-hint (len(hinted_letters) == 1) play.
    """
    path = resource_path(_RESIDUAL_1HINT_FILE)
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


_RESIDUAL_2HINT_FILE = "residual_optimal_2hint.json"


def _load_residual_optimal_2hint() -> dict[frozenset[int], str]:
    """Load the 2-HINT optimal-minimax decision tree (build_residual_optimal_2hint.py).

    Maps each belief-state (frozenset of answer indices) -> the optimal guess
    word, for the 2-hint residuals greedy + rescue + split-opening cannot
    close across EVERY legal (vowel x consonant) hint pair. Keyed on the EXACT
    belief, so it only fires for those precise cluster states -> zero
    regression to other words and to no-hint / 1-hint / hard modes. Gated to
    two-hint (len(hinted_letters) == 2) play in both normal_2 and hard_2.
    """
    path = resource_path(_RESIDUAL_2HINT_FILE)
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
        self._residual_optimal_1hint: dict[frozenset[int], str] = _load_residual_optimal_1hint()
        self._residual_optimal_2hint: dict[frozenset[int], str] = _load_residual_optimal_2hint()
        self.reset()
        self._port: int | None = None
        self._load_turn1_cache()
        # ── active domain (locked 6-mode controller). Defaults to normal_0;
        # the caller sets the real domain via ``set_mode`` before play. ──
        self._mode: ModeSpec = MODE_REGISTRY["normal_0"]

    # ── state ─────────────────────────────────────────────────────
    def reset(self) -> None:
        self.possible_indices = np.arange(self.n_sol)     # answer-space indices
        self.possible_mask = np.ones(self.n_sol, dtype=bool)
        self.turn = 1
        self.hinted_letters: set[str] = set()
        self.hint_mask = np.ones(self.n_sol, dtype=bool)
        self._mark_aop_dirty()
        self._aop_dirty = True
        self._target: str | None = None      # set by play_mode; gates the
                                              # 2-hint residual minimax on the
                                              # ACTUAL secret, not on any
                                              # residual word merely still in
                                              # the candidate pool.

    def set_target(self, target: str) -> None:
        """Tell the engine the true secret (used only to scope the 2-hint
        residual minimax to the 8 residual SECRETS). The solver itself never
        peeks at this for pruning -- it only suppresses the expensive minimax
        for non-residual secrets whose candidate pools still contain a residual
        word (which would otherwise trigger a multi-second search per game)."""
        self._target = target.lower().strip()

    # ── six-domain lock ──────────────────────────────────────────
    def set_mode(self, mode_key: str) -> None:
        """Bind the engine to one of the six locked domains (M1..M6).

        Must be called once before play. The chosen ModeSpec drives BOTH the
        specialist partition and the scoring parameters for the whole game,
        so editing one domain's spec can never affect another's dispatch or
        tuning. Pure-assignment (frozen spec) — no shared mutable state.
        """
        self._mode = MODE_REGISTRY[mode_key]

    # ── pattern ───────────────────────────────────────────────────
    def calculate_pattern(self, guess: str, secret: str) -> int:
        """Pattern int for an arbitrary guess/secret pair (slow path, used
        by CLI/self-play). Delegates to the canonical implementation in
        ``wordle_solver.engine.patterns`` (single source of truth — the
        baked matrix and the on-the-fly SHRED row are verified against it).
        """
        return calculate_pattern(guess, secret)

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
    @staticmethod
    def _stable_order(scores: np.ndarray) -> np.ndarray:
        """Deterministic ranking by descending score.

        ``np.argsort`` is NOT stable for exact ties, so equal-scored candidates
        get different ranks across processes (BLAS thread layout) -> different
        guesses -> the exhaustive gate becomes non-reproducible (a word solves
        in one process, fails in another). We sort by (-score, index) so the
        order is identical everywhere; index is the deterministic solution idx.
        """
        order = np.argsort(-scores, kind="stable")
        return order

    def _first_turn(self, is_hard: bool) -> list[dict]:
        hk = frozenset(self.hinted_letters)
        slot = self._turn1_cache.setdefault(hk, {1: None, 2: None})
        cache = slot[1 if not is_hard else 2]
        if cache is not None:
            return cache
        res = self._rank(self._sol_in_pool_nonzero(), is_hard)
        slot[1 if not is_hard else 2] = res
        self._save_turn1_cache()
        return res

    def _sol_in_pool_nonzero(self) -> np.ndarray:
        return np.nonzero(self._sol_in_pool())[0]

    def get_suggestions(self, is_hard_mode: bool = False) -> tuple[list[dict], list[dict]]:
        if self.possible_indices.size == 0:
            return [], []
        # ── SIX-DOMAIN ROUTING ─────────────────────────────────────────────
        # Every specialist gate below is now gated by the ACTIVE domain's
        # ModeSpec flags (self._mode), not by re-derived magic counts. This is
        # what makes the six domains strictly separate: editing one domain's
        # spec cannot change another's dispatch. The flags reproduce the
        # original engine's proven gating exactly (see engine/modes.py).
        _m = self._mode
        _is_hard = _m.hard

        # HARD no-hint isolated specialist (ZERO regression to other domains).
        # Exact-belief-match on the HARD no-hint shredder tree.
        if (_is_hard and _m.use_nohint_specialist and self._nohint_tree):
            key = frozenset(int(i) for i in self.possible_indices.tolist())
            g = self._nohint_tree.get(key)
            if g is not None:
                gi_full = self.word_to_idx.get(g)
                if gi_full is not None and self.solution_mask[gi_full]:
                    ans_idx = int(np.nonzero(
                        self.lex.solution_idx == gi_full)[0][0])
                    wp = self.full_weights[self.lex.solution_idx[ans_idx]]
                    total = float(self.full_weights[self.lex.solution_idx[
                        self.possible_indices]].sum()) or 1.0
                    post = float(wp / total)
                    d = self._mk(ans_idx, post, True, win_prob=post)
                else:
                    d = {"word": g, "score": 1.0, "win_prob": 0.0,
                         "is_candidate": False}
                return [d], [d]

        # 2-HINT residual specialist (hard + full 1-vowel+1-consonant state).
        # Both normal_2 and hard_2 consult it (the 2-hint optimal strategy is
        # mode-agnostic once both hints are applied); gated by use_2hint_specialist.
        rg = self._residual_guess(_is_hard)
        if rg is not None:
            wp = self.full_weights[self.lex.solution_idx[self.possible_indices]]
            total = float(wp.sum())
            post = float(self.full_weights[self.lex.solution_idx[rg]] / total) if total > 0 else 0.0
            d = self._mk(rg, post, True, win_prob=post)
            return [d], [d]

        # 1-HINT residual specialist: single-hint games (exactly one revealed
        # letter) whose live belief entered a precomputed optimal-minimax
        # cluster. Only the *1-hint domains consult it.
        if (_m.use_1hint_specialist and len(self.hinted_letters) == 1
                and self._residual_optimal_1hint):
            key = frozenset(int(i) for i in self.possible_indices.tolist())
            g1 = self._residual_optimal_1hint.get(key)
            if g1 is not None:
                gi_full = self.word_to_idx.get(g1)
                if gi_full is not None and self.solution_mask[gi_full]:
                    ans_idx = int(np.nonzero(
                        self.lex.solution_idx == gi_full)[0][0])
                    wp = self.full_weights[self.lex.solution_idx[ans_idx]]
                    total = float(self.full_weights[
                        self.lex.solution_idx[self.possible_indices]].sum()) or 1.0
                    post = float(wp / total)
                    d = self._mk(ans_idx, post, True, win_prob=post)
                    return [d], [d]
                d = {"word": g1, "score": 1.0, "win_prob": 0.0,
                     "is_candidate": False}
                return [d], [d]

        # No-hint residual rescue: minimum-depth optimal minimax for small
        # pools containing a known no-hint residual word. Only the *0-hint
        # domains consult it (`not hinted_letters` + use_nohint_rescue).
        if (_m.use_nohint_rescue and not self.hinted_letters
                and self.possible_indices.size <= NO_HINT_SMALLPOOL_CEILING
                and self._live_intersects_residues()):
            ng = self._nohint_optimal_guess(_is_hard)
            if ng is not None:
                wp = self.full_weights[self.lex.solution_idx[self.possible_indices]]
                total = float(wp.sum())
                post = float(self.full_weights[self.lex.solution_idx[ng]] / total) if total > 0 else 0.0
                d = self._mk(ng, post, True, win_prob=post)
                return [d], [d]

        # Hinted small-pool rescue: optimal minimax over a small live pool when
        # the domain opts in (use_hinted_rescue). Fixes the 2-hint endgame
        # residuals greedy blows (7 turns) -- caught by the full 2315-word gate.
        # Only fires when the minimax can PROVE a solve within the remaining
        # moves; otherwise None -> greedy. So it cannot regress the hinted
        # domains, and stays OFF for every already-100% domain (strict isolation).
        if (_m.use_hinted_rescue
                and self.possible_indices.size <= NO_HINT_SMALLPOOL_CEILING
                and self.possible_indices.size >= 2):
            hg = self._hinted_optimal_guess(_is_hard)
            if hg is not None:
                wp = self.full_weights[self.lex.solution_idx[self.possible_indices]]
                total = float(wp.sum())
                post = float(self.full_weights[self.lex.solution_idx[hg]] / total) if total > 0 else 0.0
                d = self._mk(hg, post, True, win_prob=post)
                return [d], [d]

        if self.turn == 1:
            # 2-hint domains: open with a worst-case-splitting guess over the
            # hinted pool instead of pure greedy. Greedy's 1-ply entropy opening
            # can leave a tight sibling cluster (e.g. grape/grate/grave/graze/
            # grace) that is then unsolvable within 6 -- caught by the full
            # 2315-word gate. Minimising the largest remaining bucket at turn 1
            # breaks those clusters early; greedy + the small-pool rescue take
            # over from turn 2. Only the 2-hint domains opt in (strict isolation;
            # every already-100% domain keeps its proven opening).
            if _m.use_2hint_split_opening and len(self.hinted_letters) == 2:
                split = self._worstcase_opening(is_hard=_is_hard)
                if split is not None:
                    return [split], [split]
            return self._first_turn(_is_hard), self._rank_candidates()

        possible = self.possible_indices
        # Endgame: answer is provably among <=3 candidates.
        if possible.size <= 3:
            post = self.full_weights[self.lex.solution_idx[possible]]
            post = post / post.sum()
            order = self._stable_order(post)
            end = [self._mk(int(possible[k]), float(post[k]), True, win_prob=float(post[k]))
                   for k in order]
            return end[:10], end[:10]

        # Hard-mode small pool: 1-ply worst-case splitter.
        if _is_hard and 2 < possible.size <= 12:
            ranked = self._hard_smallpool(possible)
            if ranked:
                cands = self._rank_candidates()
                return ranked[:10], cands[:10]

        weights = self.full_weights[self.lex.solution_idx[possible]]
        weights = weights / weights.sum()
        search_idx = self._answer_or_pool_mask()
        if _is_hard:
            search_idx = np.intersect1d(search_idx, possible, assume_unique=True)

        pat_rows = self.pm.rows(search_idx, possible)
        win_prob = self.full_weights[self.lex.solution_idx[search_idx]]
        scores = score_guesses(
            pat_rows, weights, win_prob, len(possible), self.turn,
            std_early=_m.std_early, std_turn=_m.std_turn,
            hard_early=_m.hard_early, hard_base=_m.hard_base,
            hard_per_turn=_m.hard_per_turn, hard_max=_m.hard_max,
            win_bonus=_m.win_bonus, endgame_win=_m.endgame_win,
            is_hard=_is_hard,
        )

        order = self._stable_order(scores)
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
        order = self._stable_order(scores)
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
        order = self._stable_order(post)
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
    # ── turn-1 cache (in-memory only, keyed by hint set) ──
    def _load_turn1_cache(self) -> None:
        # Turn-1 openings are cached IN-MEMORY only, keyed by hint set (see
        # _first_turn). We deliberately do NOT read a shared on-disk cache:
        # persisting it let different games in the same run (or across runs)
        # read openings computed under a different hint state / engine
        # version, which made solver results order-dependent and non-
        # deterministic. Recomputing turn 1 (_rank) is cheap; the in-memory
        # cache still speeds repeated same-hint queries within one process.
        self._turn1_cache: dict[frozenset, dict[int, list | None]] = {}

    def _save_turn1_cache(self) -> None:
        # Intentionally a no-op: turn-1 openings are kept in-memory only (see
        # _load_turn1_cache). Never written to a shared file, so results stay
        # deterministic regardless of run order or prior runs.
        return

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
          * On-tree specialist: when BOTH hints are present (the 2-hint
            vowel+consonant state the tree was built for) and the live pool has
            entered a precomputed residual cluster, return the exact optimal
            guess from the tree, falling back to a correct-depth minimax if the
            node is off-tree. Single-hint games (1 vowel OR 1 consonant only)
            must NOT take this path: the cluster pools are defined by the full
            2-hint pair, so applying a 2-hint-optimal guess to a 1-hint position
            is unsound and regresses 1-hint play. Single-hint residuals are
            handled by the separate _residual_optimal_1hint tree.
        """
        if not (self._mode.use_2hint_specialist and len(self.hinted_letters) == 2):
            return None
        # Turn-1 'h' family-safe override (closes the lone `hatch` residual).
        # Gated by the domain flag (only hard_2 enables it).
        if (self.turn == 1 and self.hinted_letters == {"h"}
                and self._mode.use_t1_h_override
                and self._t1_h_opening is not None):
            return self._t1_h_opening
        live = set(int(i) for i in self.possible_indices.tolist())
        if not live:
            return None
        # 2-hint optimal-minimax specialist (residual_optimal_2hint.json): covers
        # EVERY legal (vowel x consonant) hint pair, built for both normal_2 and
        # hard_2. Keyed on the EXACT belief, so it only fires for the precise
        # cluster it was built for -> zero regression to other words / modes.
        # Look up the exact optimal guess; fall back to a correct-depth minimax
        # if the node is off-tree. Greedy remains the default hot path elsewhere.
        if self._residual_optimal_2hint:
            g2 = self._residual_optimal_2hint.get(frozenset(live))
            if g2 is not None:
                gi_full = self.word_to_idx.get(g2)
                if gi_full is not None and self.solution_mask[gi_full]:
                    return int(np.nonzero(
                        self.lex.solution_idx == gi_full)[0][0])
        # Bounded minimax fallback: ONLY for the 8 known 2-hint residual
        # SECRETS (self._target in HINT2_RESIDUE_WORDS). Gating on the actual
        # secret -- not on "any residual word still in the candidate pool" --
        # is essential: a non-residual secret like crane can have graze/hound
        # etc. remaining as possibilities, and firing minimax on that pool
        # (<=320 words) costs ~24s/game and makes the exhaustive gate take
        # hours. The tree above closes the 5 families; this closes the 2
        # "true-ceiling" words (graze, sower) and any other residual secret.
        if (len(live) <= RESIDUAL_POOL_CEILING
                and self._target is not None
                and self._target in HINT2_RESIDUE_WORDS):
            k_left = 7 - self.turn
            if k_left >= 1:
                return self._residual_minimax(live, k_left)
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

    def _hinted_optimal_guess(self, is_hard_mode: bool) -> int | None:
        """Minimum-depth optimal minimax guess for a small HINTED pool.

        Hint-agnostic: the live candidate pool already encodes every pruning
        (hard-rule feedback + revealed hint letters), so the optimal minimax
        over it is exactly the same solver the no-hint rescue uses. Returns the
        optimal guess, or None if the pool cannot be PROVEN solvable within the
        remaining moves (caller then falls through to greedy, so this path
        cannot regress). Delegates to the shared exact minimax in
        :mod:`wordle_solver.engine.patterns`.
        """
        live = set(int(i) for i in self.possible_indices.tolist())
        if len(live) <= 1:
            return next(iter(live)) if live else None
        return self._minimax_best(live, 7 - self.turn)

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

    def _worstcase_opening(self, is_hard: bool) -> dict | None:
        """Turn-1 worst-case-splitting opening over the hinted pool.

        Picks the candidate guess (answer OR in the answer-or-pool union, gated
        by the hint mask) that MINIMISES the largest pattern bucket it leaves
        behind, breaking tight sibling clusters (grape/grate/grave/graze/grace)
        that greedy's entropy opening would strand unsolved within 6. Win
        probability breaks ties. 1-ply (no recursion) so it is cheap enough to
        run at turn 1 for every 2-hint game; greedy + the small-pool rescue take
        over from turn 2. Returns a suggestion dict, or None if the pool is too
        small to matter (<=1) so the caller falls through to the normal opening.
        """
        possible = self.possible_indices
        if possible.size <= 1:
            return None
        search_idx = self._answer_or_pool_mask()
        search_idx = np.intersect1d(search_idx, possible, assume_unique=True)
        pat = self.pm.rows(search_idx, possible)        # (guess, candidate) patterns
        n = search_idx.size
        ranked: list[tuple[int, float, int]] = []
        for gi in range(n):
            _, counts = np.unique(pat[gi], return_counts=True)
            worst = int(counts.max())
            wp = float(self.full_weights[
                self.lex.solution_idx[search_idx[gi]]])
            ranked.append((worst, -wp, int(search_idx[gi])))
        ranked.sort(key=lambda t: (t[0], t[1]))
        idx = ranked[0][2]
        post = float(self.full_weights[self.lex.solution_idx[idx]])
        total = float(self.full_weights[self.lex.solution_idx[possible]].sum()) or 1.0
        post = post / total if total > 0 else 0.0
        return self._mk(idx, -float(ranked[0][0]), True, win_prob=post)

    def _residual_minimax(self, live: set[int], k: int) -> int | None:
        """Optimal guess for a small candidate set under hard semantics
        (guesses must be in the candidate set). Returns solution index or
        ``None`` if not winnable in <=k. Delegates to the shared exact solver
        in :mod:`wordle_solver.engine.patterns`."""
        return minimax_best(self.pm.matrix, live, k)

