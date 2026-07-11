"""Build the answer-only pattern matrix.

Outputs ``wordle_full_matrix.npy`` as a (2315 x 2315) int16 matrix indexed
by *answer index* (``valid_solutions.csv`` order). The old builder produced
a 12,972 x 12,972 matrix via an O(n^2) pure-Python double loop (~minutes);
this computes each guess's full pattern row in one vectorized numpy call
and loops only over the 2,315 answers, so it finishes in seconds.

Usage:
    python build_matrix.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wordle_solver.utils import resource_path

_POW3 = np.array([3**i for i in range(5)], dtype=np.int16)
OUT = "wordle_full_matrix.npy"


def _row(guess_word: str, secrets: np.ndarray) -> np.ndarray:
    """Vectorized pattern ints of ``guess_word`` against every row of
    ``secrets`` (P x 5 ascii ints). Two-pass (greens, then yellows
    consuming one matched secret letter each)."""
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


def build() -> None:
    words = pd.read_csv(resource_path("scientific_word_data.csv"))["word"].tolist()
    sols = pd.read_csv(resource_path("valid_solutions.csv"))["word"].tolist()
    w2i = {w: i for i, w in enumerate(words)}
    sol_idx = [w2i[w] for w in sols]
    n = len(sols)
    M = np.zeros((n, n), dtype=np.int16)
    sec_ascii = np.array([[ord(c) for c in w] for w in sols], dtype=np.int16)
    print(f"Baking {n} x {n} answer matrix...")
    for gi, w in enumerate(sols):
        M[gi, :] = _row(w, sec_ascii)
        if gi % 250 == 0:
            print(f"  {gi}/{n}")
    np.save(resource_path(OUT), M)
    print(f"Saved {OUT}  ({M.nbytes/1e6:.1f} MB)")


if __name__ == "__main__":
    build()
