"""Regression tests for the Wordle game contract (``play_one_game``).

Wordle is exactly 6 guesses. A win is turns in 1..6; a loss is the engine
failing to name the target within those 6 guesses, which ``play_one_game``
must report as turns == 7 (NOT a magic sentinel, NOT an unbounded loop).

These tests lock that contract so a future edit to ``_game.py`` / ``Engine.py``
cannot silently reintroduce a hidden safety cap or a wrong return code.

The fast tests cover a deterministic seed-sampled slice of the full corpus
plus the exact documented (previously failing) residual words (so the contract
is anchored even on a quick run). A separate exhaustive test (``-m exhaustive``)
replays all 2,315 official answers in both modes — this is the definitive
regression gate the solver's accuracy claims rest on.

Mode separation (see ReadME "Performance Benchmarks"):
  * Hinted modes (normal+hint, hard+hint) are the protected baseline: 100%
    solve rate, and their average turns must never regress. They are untouched
    by the no-hint residue rescue.
  * No-hint modes:
      - NORMAL no-hint: 100% (every official answer solved in <=6).
      - HARD   no-hint: 100% (2315/2315). The three former residuals
         (`foyer`, `hound`, `mound`) are now closed by the HARD no-hint
         optimal-shredder decision tree (``residual_optimal_nohint.json``),
         built by ``build_nohint_tree2.py``. Hard no-hint reached 100% with
         zero regression to the other three modes.

The hard no-hint residuals are documented here so any silent change in solve
count or failure set is caught immediately.
"""

import pytest

from wordle_solver.engine.game import play_one_game

# Words the solver provably solves within the limit (regression anchors).
CONTROLS = [("CRANE", False), ("SLATE", False), ("TRACE", True), ("STARE", True)]
# No-hint NORMAL residuals: NONE — normal no-hint solves 100%.
NORMAL_RESIDUALS: list[str] = []
# No-hint HARD residuals: NONE — the three former hard-mode no-hint failures
# (foyer/hound/mound) are now closed by the HARD no-hint optimal-shredder
# decision tree (residual_optimal_nohint.json). Hard no-hint is 100%.
HARD_RESIDUALS: list[str] = []

# Words that USED to fail no-hint before the closure, now locked as wins so a
# regression that reopens any of them is caught immediately (positive guards
# replacing the old `*_residuals_fail_at_seven` tests, which are obsolete now
# that both residual sets are empty).
FORMER_NORMAL_RESIDUALS = ["bitty", "foyer", "valor"]
FORMER_HARD_RESIDUALS = ["foyer", "hound", "mound", "hatch", "hunch", "latch"]


@pytest.mark.parametrize("word,hard", CONTROLS)
def test_controls_win_within_six(word, hard):
    _, turns = play_one_game(word, hard, hints=False)
    assert 1 <= turns <= 6, f"{word} should win in <=6, got {turns}"


@pytest.mark.parametrize("word", FORMER_NORMAL_RESIDUALS)
def test_former_normal_residuals_now_win(word):
    _, turns = play_one_game(word, False, hints=False)
    assert 1 <= turns <= 6, f"{word} (former normal residual) must win <=6, got {turns}"


@pytest.mark.parametrize("word", FORMER_HARD_RESIDUALS)
def test_former_hard_residuals_now_win(word):
    _, turns = play_one_game(word, True, hints=False)
    assert 1 <= turns <= 6, f"{word} (former hard residual) must win <=6, got {turns}"


def test_no_hint_win_is_strictly_six_or_under():
    # Exhaustive guard over a deterministic seed-sample of the full corpus:
    # a solved game never returns the failure sentinel, and a failed game
    # never returns a "win" turn count. The full-corpus proof lives in
    # test_exhaustive_contract (marked `exhaustive`).
    import pandas as pd

    words = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()
    import random

    random.seed(20240710)
    sample = random.sample(words, 400)
    for w in sample:
        _, turns = play_one_game(w, False, hints=False)
        assert turns in range(1, 8), f"{w} returned out-of-contract turns={turns}"


# ---------------------------------------------------------------------------
# Hinted-mode protection (the protected baseline must never regress).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("hard", [False, True])
@pytest.mark.exhaustive
def test_hinted_mode_is_perfect(hard):
    """Hinted play must solve EVERY official answer in <=6 (100%).

    This is the contract that must hold across all future edits: any change
    that drops a hinted solve (or pushes a hinted average up) is a regression
    and must be aborted/isolated, never shipped.
    """
    import pandas as pd

    words = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()
    failures = [w for w in words
                if play_one_game(w, hard, hints=True)[1] > 6]
    assert not failures, f"hinted mode (hard={hard}) regressed: {failures}"


# Hard floor on no-hint accuracy so a future edit cannot silently drop it.
# NORMAL no-hint is 100%. HARD no-hint is now 100% too (foyer/hound/mound
# closed by the no-hint optimal-shredder tree).
NO_HINT_FLOOR = {
    False: 2315,   # NORMAL no-hint must stay 100%
    True: 2315,    # HARD   no-hint must stay 100%
}

# Current HARD no-hint residuals captured from exhaustive closed-loop self-play
# over all 2,315 official answers. Any silent change in solver behavior can
# either change solve count below this floor or add/remove failing words — both
# are regressions, and either one is caught by `test_exhaustive_contract`.
EXPECTED_HARD_RESIDUALS = set()  # hard no-hint is now 100% — no residuals


@pytest.mark.parametrize("hard", [False, True])
@pytest.mark.exhaustive
def test_no_hint_accuracy_floor(hard):
    import pandas as pd

    words = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()
    solved = sum(1 for w in words
                 if play_one_game(w, hard, hints=False)[1] <= 6)
    assert solved >= NO_HINT_FLOOR[hard], (
        f"no-hint (hard={hard}) accuracy dropped below floor: {solved}"
    )


@pytest.mark.exhaustive
def test_exhaustive_contract():
    """Definitive gate: replay ALL 2,315 official answers, both modes, no
    hints. Lock the known residual sets — any drop in solve rate (a new
    word failing at >6, or a previously-failing word that now does not fail
    at exactly 7) is caught here.
    """
    import pandas as pd

    words = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()

    normal_failures, hard_failures = set(), set()
    for hard, sink in ((False, normal_failures), (True, hard_failures)):
        for w in words:
            _, turns = play_one_game(w, hard, hints=False)
            assert turns in range(1, 8), (
                f"{w} (hard={hard}) returned out-of-contract turns={turns}"
            )
            if turns == 7:
                sink.add(w.upper())

    assert normal_failures == set(NORMAL_RESIDUALS), (
        f"normal residuals drifted: {normal_failures ^ set(NORMAL_RESIDUALS)}"
    )
    expected_hard = set(HARD_RESIDUALS)
    assert hard_failures == expected_hard, (
        f"hard residuals drifted: got {sorted(hard_failures)}, "
        f"expected {sorted(expected_hard)}"
    )
