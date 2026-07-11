"""Word data + the answer-only pattern matrix.

The solver's candidate universe is the set of valid NYT answers (2,315
words), NOT the full 12,972-word dictionary. We therefore bake a
*2315 x 2315* integer pattern matrix (≈5.4 MB) indexed by answer, which is
what scoring actually consumes — 1/31st the size of the old full matrix and
31x faster to build.

Guesses outside the answer set (SHRED openers like "roate") are still
scored correctly: ``PatternMatrix.score`` computes their pattern row on the
fly via a vectorized two-pass algorithm (no per-letter Python loop).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wordle_solver.utils import resource_path

MATRIX_FILE = "wordle_full_matrix.npy"   # kept filename so the spec/.gitignore are stable
SOLUTIONS_FILE = "valid_solutions.csv"
WORDS_FILE = "scientific_word_data.csv"

# pattern encoding: grey=0, yellow=1, green=2  -> base-3 integer over 5 slots
_POW3 = np.array([3**i for i in range(5)], dtype=np.int16)


def pattern_int_to_tuple(p: int) -> tuple[int, ...]:
    return tuple((p // (3**i)) % 3 for i in range(5))


class Lexicon:
    """Immutable word data: the full dictionary plus the answer subset."""

    def __init__(self) -> None:
        df = pd.read_csv(resource_path(WORDS_FILE))
        self.all_words: list[str] = df["word"].tolist()
        self.n_all: int = len(self.all_words)
        self.word_to_idx: dict[str, int] = {w: i for i, w in enumerate(self.all_words)}
        self.probs: np.ndarray = np.maximum(df["probability"].to_numpy(float), 1e-10)
        self.probs /= self.probs.sum()

        sol_df = pd.read_csv(resource_path(SOLUTIONS_FILE))
        self.solution_words: list[str] = sol_df.iloc[:, 0].tolist()
        self.solution_idx: np.ndarray = np.array(
            [self.word_to_idx[w] for w in self.solution_words], dtype=np.int64
        )
        self.n_solutions: int = len(self.solution_words)
        # bool membership over the full dictionary
        self.solution_mask: np.ndarray = np.zeros(self.n_all, dtype=bool)
        self.solution_mask[self.solution_idx] = True


class PatternMatrix:
    """2315 x 2315 integer pattern matrix, indexed by *answer index*."""

    def __init__(self, lexicon: Lexicon) -> None:
        self.lex = lexicon
        self.matrix: np.ndarray = np.load(
            resource_path(MATRIX_FILE), mmap_mode="r"
        )
        self.ansi = lexicon.solution_idx            # answer -> full-dict index
        self.n = lexicon.n_solutions

    @property
    def answers(self) -> list[str]:
        return self.lex.solution_words

    def rows(self, guess_idx: np.ndarray, possible: np.ndarray) -> np.ndarray:
        """Dense (len(guess_idx), len(possible)) pattern ints.

        ``guess_idx`` and ``possible`` are **answer-space** indices. The
        stored matrix is row-major by guess, so each guess is one contiguous
        ~5 KB read.
        """
        return self.matrix[guess_idx][:, possible]

    def row_for(self, guess_word: str, possible: np.ndarray) -> np.ndarray:
        """Pattern row for an arbitrary dictionary word (e.g. a SHRED opener).

        Computed vectorized over all ``possible`` answers in two passes
        (greens, then yellows, consuming matched letters) — no Python
        per-letter double loop. Returns an int array of length ``len(possible)``.
        """
        g = np.frombuffer(guess_word.encode("ascii"), dtype=np.int8).astype(np.int16)
        sec = np.array(
            [[ord(c) for c in self.lex.solution_words[j]] for j in possible],
            dtype=np.int16,
        )  # (P, 5)
        # pass 1 — greens
        green = sec == g                       # (P, 5), consumes both sides
        sec[green] = -1
        g_rem = np.where(green, -1, g)         # a green guess slot can't also be yellow
        # pass 2 — yellows (consume one secret letter per yellow)
        yellow = np.zeros((possible.shape[0], 5), dtype=np.int16)
        for c in range(5):
            L = g_rem[:, c]                                   # (P,)
            has = (sec == L[:, None]).any(axis=1)             # (P,)
            flag = has & ~green[:, c]
            yellow[:, c] = flag.astype(np.int16)
            rows = np.where(flag)[0]
            if rows.size:
                match = sec[rows] == L[rows][:, None]         # (R, 5)
                first = np.argmax(match, axis=1)
                sec[rows, first] = -1                         # consume
        pat = (green.astype(np.int16) * 2 + yellow) * _POW3
        return pat.sum(axis=1).astype(np.int32)
