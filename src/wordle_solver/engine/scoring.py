"""Scoring math for the Wordle solver.

Given, for each candidate guess, a dense row of pattern ints over the
current possible-answers set, compute an information-gain / expected-cost
score per guess, entirely in numpy (one ``np.add.at`` scatter, no Python
loop over guesses).
"""
from __future__ import annotations

import numpy as np

_POW3 = np.array([3**i for i in range(5)], dtype=np.int16)
N_PATTERNS = 243
_PATTERNS = (np.arange(N_PATTERNS)[:, None] // _POW3 % 3).astype(np.int8)


def score_guesses(
    pattern_rows: np.ndarray,
    weights: np.ndarray,
    win_prob: np.ndarray,
    pool_size: int,
    turn: int,
    *,
    std_early: float,
    std_turn: float,
    hard_early: float,
    hard_base: float,
    hard_per_turn: float,
    hard_max: float,
    win_bonus: float,
    endgame_win: float,
    is_hard: bool,
) -> np.ndarray:
    """Return a float score for each guess row in ``pattern_rows``.

    ``pattern_rows`` shape: (n_guesses, n_possible), dtype int.
    ``weights``      shape: (n_possible,) candidate distribution (already
                     restricted to the possible set and renormalised).
    ``win_prob``     shape: (n_guesses,) P(guess is THE answer).
    """
    # Coerce to integer indices: np.add.at requires ints, and callers may pass
    # float-typed rows (e.g. reloaded arrays). Int callers are unaffected.
    pattern_rows = np.asarray(pattern_rows, dtype=np.intp)
    n_g, n_p = pattern_rows.shape
    counts = np.zeros((n_g, N_PATTERNS), dtype=np.float64)
    # scatter weights into the bucket of each guess's pattern
    np.add.at(counts, (np.arange(n_g)[:, None], pattern_rows), weights)

    nz = counts.copy()
    nz[nz <= 0] = 1.0
    entropy = -np.sum(counts * np.log2(nz), axis=1)
    worst_case = counts.max(axis=1)

    if is_hard:
        early = hard_early
        penalty = min(hard_max, hard_base + turn * hard_per_turn)
    else:
        early = std_early
        penalty = std_turn  # single flat constant in std mode
        if turn >= 3:
            penalty = max(0.0, std_turn - (turn - 2) * 0.15)

    if pool_size <= 2:
        return entropy + endgame_win * win_prob
    if pool_size <= 10 and is_hard:
        # Hard mode only: every pool member is a legal guess, so once the
        # pool is this small the answer is almost surely among them — pick
        # the most probable instead of wasting turns on near-identical
        # siblings (which the 6-turn cap punishes fatally). Normal mode keeps
        # its discrimination strategy (it can use non-pool SHRED words).
        return -100.0 * worst_case + 0.01 * entropy + win_prob
    if pool_size <= 5:
        return -100.0 * worst_case + 0.01 * entropy + win_prob
    if turn <= 2:
        return entropy - early * worst_case
    return entropy - penalty * worst_case + win_bonus * win_prob
