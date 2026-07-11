"""Tests for lexicon.py — the word data + answer-only pattern matrix.

The matrix is the single most expensive artifact and the one piece of new
math with no direct coverage. We verify it against the brute-force
``calculate_pattern`` (Wordle's canonical two-pass algorithm) on random
samples, for BOTH stored (answer) and on-the-fly (SHRED) guesses.
"""
import random

import numpy as np
import pandas as pd
import pytest

from wordle_solver.engine.lexicon import Lexicon, PatternMatrix
from wordle_solver.engine import WordleEngine

SOLUTIONS = pd.read_csv("valid_solutions.csv")["word"].tolist()
ALL_WORDS = pd.read_csv("valid_guesses.csv")["word"].tolist()


@pytest.fixture(scope="module")
def lex():
    return Lexicon()


@pytest.fixture(scope="module")
def engine():
    return WordleEngine()


def _brute(guess: str, secret: str) -> int:
    p: list[int] = [0] * 5
    sl: list[str | None] = list(secret)
    gl: list[str | None] = list(guess)
    for i in range(5):
        if gl[i] == sl[i]:
            p[i] = 2; sl[i] = None; gl[i] = None
    for i in range(5):
        if gl[i] is not None and gl[i] in sl:
            p[i] = 1; sl[sl.index(gl[i])] = None
    return sum(p[i] * (3**i) for i in range(5))


class TestLexicon:
    def test_counts(self, lex):
        assert lex.n_all == len(lex.all_words)
        assert lex.n_all >= len(SOLUTIONS)
        assert lex.n_solutions == len(SOLUTIONS)
        assert len(lex.solution_words) == len(SOLUTIONS)

    def test_probs_normalised(self, lex):
        assert abs(lex.probs.sum() - 1.0) < 1e-6
        assert abs(lex.solution_mask.sum() - len(SOLUTIONS)) < 1e-6

    def test_solution_idx_is_subset(self, lex):
        # every solution word maps to an index inside the full word array
        for w in SOLUTIONS:
            assert lex.word_to_idx[w] == lex.solution_idx[lex.solution_words.index(w)]


class TestPatternMatrix:
    def test_matrix_shape_and_dtype(self, lex):
        pm = PatternMatrix(lex)
        assert pm.matrix.shape == (len(SOLUTIONS), len(SOLUTIONS))
        assert pm.matrix.dtype == np.int16

    def test_matrix_matches_bruteforce(self, lex):
        pm = PatternMatrix(lex)
        r = random.Random(7)
        for _ in range(200):
            a, b = r.sample(SOLUTIONS, 2)
            ai = lex.solution_words.index(a)
            bi = lex.solution_words.index(b)
            assert int(pm.matrix[ai, bi]) == _brute(a, b)

    def test_row_for_answer_equals_matrix_row(self, lex):
        pm = PatternMatrix(lex)
        r = random.Random(11)
        possible = np.array(r.sample(range(len(SOLUTIONS)), 40))
        g = r.choice(SOLUTIONS)
        gi = lex.solution_words.index(g)
        got = pm.row_for(g, possible)
        assert got.dtype == np.int32
        assert np.array_equal(got, pm.matrix[gi, possible])

    def test_row_for_nonanswer_matches_bruteforce(self, lex):
        """The SHRED on-the-fly path (guess is NOT an answer) is the path
        with no prior coverage — verify it against brute force."""
        pm = PatternMatrix(lex)
        non_answers = [w for w in ALL_WORDS if w not in set(SOLUTIONS)]
        r = random.Random(21)
        for _ in range(60):
            g = r.choice(non_answers)
            possible = np.array(r.sample(range(len(SOLUTIONS)), 25))
            got = pm.row_for(g, possible)
            for k, ai in enumerate(possible):
                assert int(got[k]) == _brute(g, lex.solution_words[ai])

    def test_rows_batch_matches_loop(self, lex):
        pm = PatternMatrix(lex)
        r = random.Random(99)
        idx = np.array(r.sample(range(len(SOLUTIONS)), 30))
        possible = np.array(r.sample(range(len(SOLUTIONS)), 20))
        batch = pm.rows(idx, possible)
        for k, gi in enumerate(idx):
            assert np.array_equal(batch[k], pm.matrix[gi, possible])


class TestEnginePatternRowDispatch:
    def test_dispatch_answer_uses_matrix(self, engine):
        r = random.Random(5)
        a, b = r.sample(SOLUTIONS, 2)
        ai = engine.lex.solution_words.index(a)
        possible = np.array([engine.lex.solution_words.index(b)])
        row = engine._pattern_row(a, possible)
        assert int(row[0]) == int(engine.pm.matrix[ai, possible][0])

    def test_dispatch_nonanswer_uses_row_for(self, engine):
        non_answers = [w for w in ALL_WORDS if w not in set(SOLUTIONS)]
        r = random.Random(8)
        g = r.choice(non_answers)
        possible = np.array(r.sample(range(len(SOLUTIONS)), 15))
        row = engine._pattern_row(g, possible)
        brute = [engine.calculate_pattern(g, engine.lex.solution_words[i]) for i in possible]
        assert np.array_equal(row, np.array(brute, dtype=np.int32))
