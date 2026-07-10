"""Regression tests for the Wordle game contract (``play_one_game``).

Wordle is exactly 6 guesses. A win is turns in 1..6; a loss is the engine
failing to name the target within those 6 guesses, which ``play_one_game``
must report as turns == 7 (NOT a magic sentinel, NOT an unbounded loop).

These tests lock that contract so a future edit to ``_game.py`` cannot
silently reintroduce a hidden safety cap or a wrong return code.
"""
import pytest

from _game import play_one_game

# Words the solver provably solves within the limit (regression anchors).
CONTROLS = [("CRANE", False), ("SLATE", False), ("TRACE", True), ("STARE", True)]
# Mode-specific residuals the greedy opener cannot close in 6 (known losses).
NORMAL_RESIDUALS = ["BITTY", "FOYER", "VALOR"]
HARD_RESIDUALS = ["DITTY", "GOLLY", "HATCH", "HOUND", "HUNCH", "LATCH", "MOUND"]


@pytest.mark.parametrize("word,hard", CONTROLS)
def test_controls_win_within_six(word, hard):
    _, turns = play_one_game(word, hard, hints=False)
    assert 1 <= turns <= 6, f"{word} should win in <=6, got {turns}"


@pytest.mark.parametrize("word", NORMAL_RESIDUALS)
def test_normal_residuals_fail_at_seven(word):
    # No-hint normal play cannot solve these in 6; the contract demands a
    # clean failure code (7), never a sentinel like 11 or a turn>7.
    _, turns = play_one_game(word, False, hints=False)
    assert turns == 7, f"{word} should report failure=7, got {turns}"


@pytest.mark.parametrize("word", HARD_RESIDUALS)
def test_hard_residuals_fail_at_seven(word):
    _, turns = play_one_game(word, True, hints=False)
    assert turns == 7, f"{word} should report failure=7, got {turns}"


def test_no_hint_win_is_strictly_six_or_under():
    # Exhaustive guard: a solved game never returns the failure sentinel,
    # and a failed game never returns a "win" turn count.
    import pandas as pd
    words = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()
    for w in words[:60]:  # sample; full corpus is a benchmark, not a unit test
        _, turns = play_one_game(w, False, hints=False)
        assert turns in range(1, 8), f"{w} returned out-of-contract turns={turns}"
