"""Canonical pattern math + the shared exact minimax solver.

This module is the SINGLE SOURCE OF TRUTH for:

  * ``calculate_pattern`` — the canonical two-pass base-3 pattern int for any
    (guess, secret) pair. Used by the CLI, by headless self-play, and by the
    matrix self-tests.
  * ``minimax_best`` / ``build_optimal_table`` — the exact minimum-worst-case
    optimal solver. It is used by BOTH the engine's no-hint rescue
    (``Engine._nohint_optimal_guess`` / ``_residual_guess``) AND the offline
    residual builders (``generators/build_residual_optimal.py``). Having one
    implementation instead of three inlined copies prevents silent drift
    between the live solver and the artifacts it depends on.
"""

from __future__ import annotations

import numpy as np

_POW3 = np.array([3**i for i in range(5)], dtype=np.int16)
_INF = 10**9


def pattern_int_to_tuple(p: int) -> tuple[int, ...]:
    """Decode a base-3 pattern int into its 5-tuple of {0,1,2}."""
    return tuple((p // (3**i)) % 3 for i in range(5))


def calculate_pattern(guess: str, secret: str) -> int:
    """Pattern int for an arbitrary guess/secret pair (canonical algorithm).

    Grey=0, yellow=1, green=2, encoded as base-3 over the 5 positions. This is
    the reference implementation; the baked matrix and the on-the-fly SHRED
    row are verified against it in ``test_lexicon``.
    """
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


def _solve(matrix, S, budget, cache, guess_set):
    """Return (min_worst_case_depth, best_guess_idx) for answer-set ``S``.

    ``matrix`` is the (n_sol x n_sol) answer-space pattern-int array.
    ``guess_set(S)`` yields the legal guess indices at node ``S`` (in NYT hard
    mode this is the current sub-pool; in normal mode the same pool words are
    avg-optimal and always legal). Memoised on (frozenset(S), budget).
    """
    key = (frozenset(S), budget)
    if key in cache:
        return cache[key]
    if len(S) == 1:
        cache[key] = (1, next(iter(S)))
        return cache[key]
    if budget <= 1:
        cache[key] = (_INF, None)
        return cache[key]
    overall = _INF
    pick = None
    for gi in guess_set(S):
        row = matrix[gi]
        parts: dict[int, set[int]] = {}
        for t in S:
            p = int(row[t])
            parts.setdefault(p, set()).add(t)
        worst = 0
        feasible = True
        for bucket in parts.values():
            if len(bucket) == 1:
                d = 1
            else:
                d = _solve(matrix, frozenset(bucket), budget - 1, cache, guess_set)[0]
            if d >= _INF:
                feasible = False
                break
            worst = max(worst, d)
        if not feasible:
            continue
        cand = worst + 1
        if cand < overall:
            overall = cand
            pick = gi
    cache[key] = (overall, pick)
    return cache[key]


def minimax_best(matrix, live, k, guess_indices=None) -> int | None:
    """Optimal guess (solution index) that forces identification of the secret
    in the fewest worst-case moves, provided that is <= ``k``; else ``None``.

    ``live`` is a set/iterable of answer-space indices. ``guess_indices`` (if
    given) is a FIXED candidate set used at every node; when omitted the
    legal guesses are the current sub-pool (NYT-hard-correct and avg-optimal
    for small pools), which is the behaviour the engine and the offline
    builders both rely on.
    """
    if len(live) <= 1:
        return next(iter(live)) if live else None
    gs = (lambda S: sorted(S)) if guess_indices is None else (lambda S: guess_indices)
    depth, guess = _solve(matrix, frozenset(live), k, {}, gs)
    return guess if depth < _INF else None


def build_optimal_table(matrix, pool, kmax, guess_indices=None) -> dict[frozenset[int], int]:
    """Full optimal decision table: frozenset(subpool) -> optimal guess idx,
    for the root ``pool`` and every recursively-reachable sub-pool.
    """
    gs = (lambda S: sorted(S)) if guess_indices is None else (lambda S: guess_indices)
    cache: dict = {}
    table: dict[frozenset[int], int] = {}

    def walk(S, bud):
        depth, guess = _solve(matrix, frozenset(S), bud, cache, gs)
        if guess is None or depth >= _INF:
            return
        key = frozenset(S)
        if key in table:
            return
        table[key] = guess
        row = matrix[guess]
        parts: dict[int, set[int]] = {}
        for t in S:
            p = int(row[t])
            parts.setdefault(p, set()).add(t)
        for bucket in parts.values():
            if len(bucket) <= 1:
                continue
            walk(bucket, bud - 1)

    walk(pool, kmax)
    return table
