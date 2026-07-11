"""Tests for scoring.score_guesses — the information-gain math.

We assert invariants rather than exact scores, because the penalty
constants in Engine.py are tunables (validated by benchmark.py). What must
always hold:

  * one score per guess row, matching the input shape
  * entropy-only vs worst-case behaviour: a guess that splits the pool
    (high entropy, low worst-case) must outrank a guess that leaves one
    giant bucket (zero entropy)
  * endgame shortcut (pool_size <= 2): score == entropy + endgame_win*win_prob
  * monotonic penalty: a larger worst-case bucket lowers the score
"""
import numpy as np
import pytest

from wordle_solver.engine.scoring import score_guesses, N_PATTERNS, _PATTERNS
from wordle_solver.engine import (
    STD_EARLY_WC_PENALTY, STD_TURN_PENALTY, HARD_EARLY_WC_PENALTY,
    HARD_BASE_PENALTY, HARD_PENALTY_PER_TURN, HARD_MAX_PENALTY,
    WIN_BONUS_WEIGHT, ENDGAME_WIN_BONUS,
)


KW = dict(
    std_early=STD_EARLY_WC_PENALTY, std_turn=STD_TURN_PENALTY,
    hard_early=HARD_EARLY_WC_PENALTY, hard_base=HARD_BASE_PENALTY,
    hard_per_turn=HARD_PENALTY_PER_TURN, hard_max=HARD_MAX_PENALTY,
    win_bonus=WIN_BONUS_WEIGHT, endgame_win=ENDGAME_WIN_BONUS,
)


def test_output_shape_matches_rows():
    n_g, n_p = 7, 12
    rows = np.random.randint(0, N_PATTERNS, size=(n_g, n_p), dtype=np.int16)
    weights = np.full(n_p, 1.0 / n_p)
    win = np.full(n_g, 0.1)
    scores = score_guesses(rows, weights, win, n_p, 1, is_hard=False, **KW)
    assert scores.shape == (n_g,)
    assert np.isfinite(scores).all()


def test_entropy_beats_worstcase():
    """A guess that splits the pool must outrank one that concentrates it."""
    # two candidates; pattern rows for 2 guesses over 2 candidates
    # guess A splits perfectly: patterns {p0, p1} (entropy high, wc=0.5)
    # guess B gives same pattern to both: {p0, p0} (entropy 0, wc=1.0)
    rows = np.array([
        [0, 1],          # guess A: distinct patterns
        [0, 0],          # guess B: identical patterns
    ], dtype=np.int16)
    weights = np.array([0.5, 0.5])
    win = np.array([0.0, 0.0])
    scores = score_guesses(rows, weights, win, 2, 3, is_hard=False, **KW)
    assert scores[0] > scores[1]


def test_endgame_returns_entropy_plus_winprob():
    """pool_size <= 2 uses the endgame formula: entropy + endgame_win*win_prob."""
    rows = np.array([[0, 1], [5, 7]], dtype=np.int16)
    weights = np.array([0.5, 0.5])
    win = np.array([0.3, 0.9])
    scores = score_guesses(rows, weights, win, 2, 5, is_hard=False, **KW)
    # hand-computed entropy: both rows have 2 distinct, equiprobable buckets
    import math
    expected_entropy = -2 * (0.5 * math.log2(0.5))
    assert scores[0] == pytest.approx(expected_entropy + ENDGAME_WIN_BONUS * 0.3)
    assert scores[1] == pytest.approx(expected_entropy + ENDGAME_WIN_BONUS * 0.9)


def test_small_pool_prefers_worstcase_penalty():
    """pool_size <= 5: scoring is dominated by worst-case, not entropy."""
    rows = np.array([
        [0, 0, 1, 1, 1],   # guess A: worst-case bucket = 0.6
        [0, 1, 2, 3, 4],   # guess B: worst-case bucket = 0.2, higher entropy
    ], dtype=np.int16)
    weights = np.full(5, 0.2)
    win = np.array([0.0, 0.0])
    scores = score_guesses(rows, weights, win, 5, 2, is_hard=False, **KW)
    # lower worst-case must win, even though B has more entropy
    assert scores[0] < scores[1]


def test_hard_mode_penalty_steeper():
    """Same inputs, hard mode should penalise worst-case more than normal.

    At pool_size > 5 and turn >= 3 the scoring branches on is_hard (normal
    uses STD_TURN_PENALTY, hard uses HARD_BASE + turn*HARD_PER_TURN capped at
    HARD_MAX), so the hard score must be lower for an identical worst-case.
    """
    # 12 candidates, identical pattern across all -> zero entropy, worst-case=1
    rows = np.zeros((1, 12), dtype=np.int16)
    weights = np.full(12, 1.0 / 12)
    win = np.array([0.0])
    normal = score_guesses(rows, weights, win, 12, 3, is_hard=False, **KW)
    hard = score_guesses(rows, weights, win, 12, 3, is_hard=True, **KW)
    assert hard[0] < normal[0]


def test_pattern_constant_decode_roundtrip():
    """Every pattern int decodes to a 5-tuple of (0,1,2)."""
    assert _PATTERNS.shape == (N_PATTERNS, 5)
    for v in (0, 1, 2):
        assert set(_PATTERNS[:, v].tolist()) <= {0, 1, 2}
    # 242 == all green
    assert int(np.sum(_PATTERNS[242] * (3 ** np.arange(5)))) == 242


def test_accepts_float_typed_rows():
    """Boundary robustness: a float-typed pattern array (e.g. a reloaded
    .npy) must be coerced, not crash np.add.at with an IndexError."""
    rows = np.array([[0, 1], [0, 0]], dtype=np.float64)
    weights = np.array([0.5, 0.5])
    win = np.array([0.0, 0.0])
    scores = score_guesses(rows, weights, win, 2, 3, is_hard=False, **KW)
    assert scores.shape == (2,)
    assert np.isfinite(scores).all()
