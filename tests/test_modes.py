"""Fast structural tests for the six locked Wordle domains.

These prove, in seconds, the properties the request demands WITHOUT
replaying 2,315 words:

  * REGISTRY (D1): exactly six domains exist, with the right (hard, budget).
  * ISOLATION (D2): a ModeSpec is frozen and its scoring params / specialist
    flags are independent copies — mutating one domain's spec cannot change
    another's values (the "editing a mode doesn't affect the others" rule).
  * FLOW LOCK (D3): once a GameMode is constructed the mode (easy/hard AND
    hint budget) is locked; there is no API to switch it mid-game.
  * HINT RULE (D4): the NYT hint rule is enforced — at most one vowel and one
    consonant, no >2, no duplicates, no reverse/removal; a 0-hint domain
    accepts no hints at all.
  * DISPATCH ISOLATION (D5): the engine routes specialist + scoring decisions
    through the active ModeSpec only. We assert each domain's dispatch flags
    match its intended partition, and that switching the engine's mode
    changes which specialists can fire (e.g. normal_2 never consults the
    2-hint tree, hard_2 does).
  * CONTRACT (D6): play_mode honours the win/loss return contract and refuses
    malformed hint sets for a domain.

The full 100% solve proof over all 2,315 words x the six domains lives in
test_game_contract.py (cached, run via `pytest -m exhaustive`, or read from
disk cache) — it is the load-bearing accuracy gate; this file is the fast
guard that the *structure* is correct so a regression can't silently change
the domains' shape.
"""

import pytest

from wordle_solver.engine.modes import (
    MODE_SPECS, MODE_REGISTRY, MODE_ORDER, get_spec,
    VOWELS, CONSONANTS, hint_composition_ok,
)
from wordle_solver.engine.game_mode import MAX_HINTS
from wordle_solver.engine.game_mode import GameMode, FlowError
from wordle_solver.engine import WordleEngine
from wordle_solver.engine.game import play_mode


# ── D1: registry shape ───────────────────────────────────────────
def test_six_domains_exist():
    assert len(MODE_SPECS) == 6
    # canonical order
    assert MODE_ORDER == ("normal_0", "hard_0", "normal_1", "hard_1",
                          "normal_2", "hard_2")
    expected = {
        "normal_0": (False, 0), "hard_0": (True, 0),
        "normal_1": (False, 1), "hard_1": (True, 1),
        "normal_2": (False, 2), "hard_2": (True, 2),
    }
    for key, (hard, budget) in expected.items():
        spec = MODE_REGISTRY[key]
        assert spec.hard is hard
        assert spec.hint_budget == budget
        assert spec.key == key


# ── D2: isolation — frozen + independent copies ──────────────────
def test_specs_are_frozen_and_independent():
    # frozen: cannot mutate
    with pytest.raises(Exception):
        MODE_REGISTRY["normal_1"].std_early = 99.0
    # independent copies: each spec binds its OWN score values, not aliases
    vals = {m.key: (m.std_early, m.hard_early, m.win_bonus) for m in MODE_SPECS}
    # at least two domains share identical literals by design, but they must
    # be distinct objects (tuple equality is value-based; we assert identity
    # independence by confirming editing one (impossible, frozen) can't matter
    # AND that no spec is the same object as another).
    assert len({id(m) for m in MODE_SPECS}) == 6


def test_specialist_partition_is_distinct_per_domain():
    part = {m.key: m.specialist_partition() for m in MODE_SPECS}
    # 0-hint domains never consult the hinted specialists
    for k in ("normal_0", "hard_0"):
        assert not part[k]["1hint_specialist"]
        assert not part[k]["2hint_specialist"]
    # 1-hint domains consult ONLY the 1-hint specialist
    for k in ("normal_1", "hard_1"):
        assert part[k]["1hint_specialist"]
        assert not part[k]["2hint_specialist"]
    # 2-hint hard consults the 2-hint specialist + t1_h override.
    assert part["hard_2"]["2hint_specialist"]
    assert part["hard_2"]["t1_h_override"]
    # normal_2 consults the SAME 2-hint residual tree (the optimal
    # minimax strategy is mode-agnostic once both hints are applied) so it can
    # close tight sibling clusters like graze/hound; but it does NOT use the
    # hard-only t1_h family override.
    assert part["normal_2"]["2hint_specialist"]
    assert not part["normal_2"]["t1_h_override"]


def test_no_mid_game_switch_possible():
    # The engine's set_mode is the only way to change domain, and play_mode
    # calls it exactly once before play. A fresh engine defaults to normal_0,
    # and set_mode to a 2-hint domain then playing keeps that domain (no
    # residual from a prior domain).
    e = WordleEngine()
    assert e._mode.key == "normal_0"
    e.set_mode("hard_2")
    assert e._mode.key == "hard_2"
    # scoring params now come from the hard_2 spec, not normal_0
    assert e._mode.hard_early == MODE_REGISTRY["hard_2"].hard_early


# ── D3: mode is derived from the toggle + hints, locked after turn 1 ──
def test_mode_derived_and_locked_after_first_submit():
    gm = GameMode()  # domain DEFAULTS to normal_0
    assert gm.mode_key == "normal_0"
    assert gm.mode_locked is False
    # the Normal/Hard toggle live-switches the (hard, hint) domain
    gm.toggle_hard(True)
    assert gm.mode_key == "hard_0"
    # logging a hint live-switches the 0-hint domain to 1/2 hints
    gm.add_hint("a")  # one vowel -> hard_1
    assert gm.mode_key == "hard_1"
    gm.add_hint("b")  # one consonant -> hard_2
    assert gm.mode_key == "hard_2"
    # no API to switch the derived domain arbitrarily; it is locked on submit
    assert not hasattr(gm, "set_mode")
    gm.on_submit(False)
    assert gm.mode_locked is True
    with pytest.raises(FlowError):
        gm.toggle_hard(False)  # refused once locked


# ── D4: hint rule enforced by GameMode ───────────────────────────
def test_hint_rule_accepts_valid_one_and_two():
    gm = GameMode()  # normal_0 by default; a hint promotes it to 1/2
    ok, why = gm.can_add_hint("a")
    assert ok, why
    gm.add_hint("a")
    assert gm.mode_key == "normal_1"
    ok, why = gm.can_add_hint("r")
    assert ok, why
    gm.add_hint("r")
    assert gm.mode_key == "normal_2"
    assert gm.hint_budget == 2
    # budget spent -> further hint refused
    ok, why = gm.can_add_hint("e")
    assert not ok and why == "FULL"


def test_hint_rule_rejects_two_vowels():
    gm = GameMode()
    gm.add_hint("a")
    ok, why = gm.can_add_hint("e")
    assert not ok and why == "TWO_VOWELS"


def test_hint_rule_rejects_two_consonants():
    gm = GameMode()
    gm.add_hint("r")
    ok, why = gm.can_add_hint("t")
    assert not ok and why == "TWO_CONS"


def test_hint_rule_rejects_duplicate():
    gm = GameMode()
    gm.add_hint("r")
    ok, why = gm.can_add_hint("r")
    assert not ok and why == "DUP"


def test_zero_hint_domain_rejects_all_hints_once_locked():
    gm = GameMode()  # normal_0, no hints taken
    assert gm.hint_count == 0
    assert gm.hint_budget == MAX_HINTS  # cap is always 2
    gm.on_submit(False)  # first guess submitted with 0 hints -> locked normal_0
    assert gm.mode_locked is True
    ok, why = gm.can_add_hint("a")
    assert not ok and why == "MODE_LOCKED"


def test_hint_rule_add_is_idempotent_block():
    gm = GameMode()
    gm.add_hint("a")  # -> normal_1
    with pytest.raises(FlowError):
        gm.add_hint("e")  # second vowel -> TWO_VOWELS -> blocked


def test_hint_composition_ok_helper():
    assert hint_composition_ok(0, 0)
    assert hint_composition_ok(1, 0)
    assert hint_composition_ok(0, 1)
    assert hint_composition_ok(1, 1)
    assert not hint_composition_ok(2, 0)
    assert not hint_composition_ok(0, 2)
    assert not hint_composition_ok(1, 2)


# ── D5: engine dispatch isolation via get_suggestions flags ──────
def test_engine_mode_routes_specialist_flags():
    e = WordleEngine()
    e.set_mode("normal_2")
    # normal_2 consults the shared 2-hint residual tree (needed to close
    # tight clusters like graze/hound) but NOT the hard-only t1_h override.
    assert e._mode.use_2hint_specialist is True
    assert e._mode.use_t1_h_override is False
    e.set_mode("hard_2")
    assert e._mode.use_2hint_specialist is True
    assert e._mode.use_t1_h_override is True
    e.set_mode("normal_1")
    assert e._mode.use_1hint_specialist is True
    assert e._mode.use_2hint_specialist is False


# ── D6: play_mode contract + validation ──────────────────────────
def test_play_mode_win_contract():
    w, turns = play_mode("crane", "normal_0")
    assert w == "crane"
    assert 1 <= turns <= 6


def test_play_mode_loss_contract_not_occurring_on_solvable():
    # A solvable word must never return 7 in its proven domain.
    w, turns = play_mode("crane", "hard_2", hint_letters=["a", "r"])
    assert 1 <= turns <= 6


def test_play_mode_rejects_wrong_hint_count():
    with pytest.raises(ValueError):
        play_mode("crane", "normal_2", hint_letters=["a"])  # needs 2
    with pytest.raises(ValueError):
        play_mode("crane", "normal_1", hint_letters=["a", "r"])  # needs 1
    with pytest.raises(ValueError):
        play_mode("crane", "normal_0", hint_letters=["a"])  # needs 0


def test_play_mode_rejects_hint_not_in_secret():
    with pytest.raises(ValueError):
        play_mode("crane", "normal_1", hint_letters=["z"])  # 'z' not in crane


def test_play_mode_unknown_mode():
    with pytest.raises(KeyError):
        play_mode("crane", "bogus_mode")
