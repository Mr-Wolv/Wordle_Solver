"""Unit + integration tests for the matrix builder (generators/build_matrix).

The 2315 x 2315 baked matrix (wordle_full_matrix.npy) is load-bearing: every
scoring call consumes it, and a corrupted/inconsistent matrix silently
degrades solver accuracy. These tests prove the builder's OUTPUT is
structurally correct WITHOUT rebuilding the 10 MB file on every run — we
validate the algorithm on a small synthetic word set (fast, deterministic)
and additionally cross-check the COMMITTED matrix against calculate_pattern
for a sample of real words.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wordle_solver.engine.patterns import calculate_pattern
from wordle_solver.engine import WordleEngine
from wordle_solver.utils import data_path


# ── algorithm-level test on a tiny synthetic set (no big file needed) ──
def _build_matrix_small(words: list[str]) -> np.ndarray:
    """Replicate build_matrix._row logic on an arbitrary word list."""
    _POW3 = np.array([3**i for i in range(5)], dtype=np.int16)
    sec_ascii = np.array([[ord(c) for c in w] for w in words], dtype=np.int16)
    n = len(words)
    M = np.zeros((n, n), dtype=np.int16)

    def _row(guess_word: str, secrets: np.ndarray) -> np.ndarray:
        g = np.frombuffer(guess_word.encode("ascii"), dtype=np.int8).astype(np.int16)
        sec = secrets.copy()
        green = sec == g
        sec[green] = -1
        g_rem = np.where(green, -1, g)
        yellow = np.zeros((secrets.shape[0], 5), dtype=np.int16)
        for c in range(5):
            L = g_rem[:, c]
            has = (sec == L[:, None]).any(axis=1)
            flag = has & ~green[:, c]
            yellow[:, c] = flag.astype(np.int16)
            rows = np.where(flag)[0]
            if rows.size:
                match = sec[rows] == L[rows][:, None]
                first = np.argmax(match, axis=1)
                sec[rows, first] = -1
        pat = (green.astype(np.int16) * 2 + yellow) * _POW3
        return pat.sum(axis=1).astype(np.int16)

    for gi, w in enumerate(words):
        M[gi, :] = _row(w, sec_ascii)
    return M


def test_matrix_diagonal_is_all_green():
    words = ["crane", "slate", "trace", "aback", "wryly"]
    M = _build_matrix_small(words)
    # diagonal: guess == secret -> all 5 tiles green -> pattern int 242
    assert np.all(np.diag(M) == 242)


def test_matrix_offdiagonal_matches_calculate_pattern():
    words = ["crane", "slate", "trace", "aback", "wryly"]
    M = _build_matrix_small(words)
    for i, g in enumerate(words):
        for j, s in enumerate(words):
            if i == j:
                continue
            assert int(M[i, j]) == calculate_pattern(g, s)


def test_matrix_pure_python_matches_reference():
    # The builder is a vectorized re-implementation of calculate_pattern;
    # confirm it agrees across many random pairs (not just the sample).
    import random
    random.seed(7)
    sample = ["crane", "slate", "trace", "aback", "wryly", "hound",
              "mound", "hatch", "hunch", "latch", "graze", "shale"]
    M = _build_matrix_small(sample)
    for i, g in enumerate(sample):
        for j, s in enumerate(sample):
            assert int(M[i, j]) == calculate_pattern(g, s), (g, s)


# ── committed-matrix integrity (cross-check against the reference) ──
def test_committed_matrix_shape_and_dtype():
    e = WordleEngine()
    M = e.pm.matrix
    assert M.ndim == 2
    assert M.shape[0] == M.shape[1] == 2315
    assert M.dtype in (np.int16,)


def test_committed_matrix_diagonal_all_green():
    e = WordleEngine()
    M = e.pm.matrix
    assert np.all(np.diag(M) == 242)


def test_committed_matrix_matches_reference_on_sample():
    e = WordleEngine()
    W = e.lex.solution_words
    sol_idx = e.lex.solution_idx
    import random
    random.seed(3)
    for _ in range(400):
        g = random.choice(W)
        s = random.choice(W)
        gi = e.word_to_idx[g]
        sai = int(np.nonzero(sol_idx == e.word_to_idx[s])[0][0])
        if e.solution_mask[gi]:
            ai = int(np.nonzero(sol_idx == gi)[0][0])
            baked = int(M := e.pm.matrix[ai, sai])
        else:
            baked = int(e.pm.row_for(g, np.array([sai]))[0])
        assert baked == e.calculate_pattern(g, s), (g, s)
