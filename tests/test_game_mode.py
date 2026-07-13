"""Tests for the game-flow controller end-state logic (engine/game_mode.py).

The 6-domain flow locks after turn 1 and ends the game at turn 6. The
exhaustive gate proves every word is *solvable*; these tests prove the
flow *state machine* itself is correct at the boundaries a happy-path gate
can't exercise:

  * a win on the final (6th) guess still counts as a win;
  * a non-win on the 6th guess flips `over` True (loss) and `won` stays False;
  * `over` blocks every further action (toggle, hint, submit);
  * reset() returns to a fresh normal_0 state.
"""

from __future__ import annotations

import pytest

from wordle_solver.engine.game_mode import GameMode, FlowError


def test_win_on_sixth_guess_is_a_win():
    gm = GameMode()
    for _ in range(5):
        gm.on_submit(False)  # turns 1..5, not solved
    assert gm.over is False
    gm.on_submit(True)       # 6th guess solves it
    assert gm.over is True
    assert gm.won is True


def test_loss_on_sixth_guess_is_over_not_won():
    gm = GameMode()
    for _ in range(5):
        gm.on_submit(False)
    gm.on_submit(False)      # 6th guess, still unsolved -> game over, loss
    assert gm.over is True
    assert gm.won is False


def test_over_blocks_hint_and_toggle_and_submit():
    gm = GameMode()
    for _ in range(6):
        gm.on_submit(False)
    assert gm.over is True
    with pytest.raises(FlowError):
        gm.toggle_hard(True)
    with pytest.raises(FlowError):
        gm.add_hint("a")
    # on_submit is idempotent once over
    gm.on_submit(True)
    assert gm.over is True
    assert gm.won is False  # a post-game submit cannot retroactively win


def test_reset_returns_fresh_normal_0():
    gm = GameMode()
    gm.toggle_hard(True)
    gm.add_hint("a")
    gm.add_hint("r")
    assert gm.mode_key == "hard_2"
    gm.on_submit(False)
    assert gm.mode_locked is True
    gm.reset()
    assert gm.mode_key == "normal_0"
    assert gm.hinted_letters == set()
    assert gm.mode_locked is False
    assert gm.over is False
    assert gm.won is False
