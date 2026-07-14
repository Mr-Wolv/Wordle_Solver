"""Shared game helper: play a single Wordle game in one of the six domains.

Both benchmark.py and profiler.py import ``play_one_game`` from here.

The six domains are STRICTLY SEPARATE (see engine/modes.py): a mode is
chosen up front and LOCKED for the whole game -- both the easy/hard axis
and the hint count. There is no mid-game mode switch and no hint
escalation. Editing one domain's configuration/data cannot affect the
others because the engine routes every specialist + scoring decision
through the active domain's frozen ModeSpec.

Public API:
  * ``play_mode(target, mode_key, hint_letters=None)`` -> (word, turns)
        The canonical entry point. ``mode_key`` is one of normal_0, hard_0,
        normal_1, hard_1, normal_2, hard_2. For hinted modes, ``hint_letters``
        supplies the exact NYT hint letters (1 vowel + 1 consonant for 2-hint;
        one letter for 1-hint) *drawn from the secret's own letters*.
  * ``play_one_game(...)`` -> (word, turns)
        Back-compat shim. ``hints=True`` maps to ``hard_2``/``normal_2``
        (auto first-vowel x first-consonant), ``hints=False`` maps to
        ``hard_0``/``normal_0``. ``hint_letters`` maps to ``*_1``/``*_2``.

Return contract (unchanged):
    (word, -1)   -- engine returned no suggestions (shouldn't happen)
    (word, 1..6) -- solved in that many turns (a Wordle win)
    (word, 7)    -- not solved within the 6-guess limit -> failure
"""

from __future__ import annotations

from typing import Iterable

from wordle_solver.engine import WordleEngine
from wordle_solver.engine.modes import (
    VOWELS, CONSONANTS, MODE_REGISTRY, get_spec,
)

# Process-local engine cache. play_mode is invoked thousands of times (once
# per (word, hint-set) in the exhaustive gate); constructing a fresh
# WordleEngine per call reloads the 2315x2315 pattern matrix + all decision
# trees (~5-7s). Reusing ONE engine per process (fully reset between games)
# makes each game ~0.1s instead of ~7s -- turning an 18-hour gate into a
# ~18-minute one. Safe: every call does set_mode + add_hint + update_state
# from a clean reset(), so there is no cross-game state leakage.
_ENGINE: WordleEngine | None = None


def _get_engine() -> WordleEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = WordleEngine()
    return _ENGINE


def _reset_shared_engine() -> None:
    """Drop the cached engine (call after importing a changed module, or in a
    fresh worker). The next play_mode call rebuilds it."""
    global _ENGINE
    _ENGINE = None


def _validate_hint_letters(word: str, hint_letters: Iterable[str] | None) -> list[str]:
    """Normalise + validate hint letters against the NYT rule.

    Returns the canonical lowercased list, asserting the hint set is a
    subset of the secret's letters and satisfies (<=1 vowel, <=1 consonant).
    """
    if not hint_letters:
        return []
    secret = set(word)
    out: list[str] = []
    nv = nc = 0
    for h in hint_letters:
        h = h.lower().strip()
        if len(h) != 1 or not h.isalpha():
            raise ValueError(f"bad hint letter: {h!r}")
        if h not in secret:
            raise ValueError(f"hint letter {h!r} not in secret {word!r}")
        if h in VOWELS:
            nv += 1
        else:
            nc += 1
        out.append(h)
    if nv > 1 or nc > 1 or (nv + nc) > 2:
        raise ValueError("NYT hint rule: at most one vowel AND one consonant")
    return out


def _play_core(
    target: str,
    mode_key: str,
    hint_letters: Iterable[str] | None = None,
    *,
    trace: bool = False,
) -> tuple[str, int, list[str]]:
    """Shared single-game loop for both ``play_mode`` and ``play_mode_trace``.

    Returns ``(word, turns, guesses)`` where ``guesses`` is the ordered list of
    guessed words (empty list when ``trace`` is False). Centralising the loop
    here means the trace path and the production path cannot drift.
    """
    spec = MODE_REGISTRY[mode_key]
    target = target.lower().strip()
    hints = _validate_hint_letters(target, hint_letters)
    if spec.hint_budget == 0 and hints:
        raise ValueError(f"mode {mode_key} takes no hints but hints={hints}")
    if spec.hint_budget == 1 and len(hints) != 1:
        raise ValueError(f"mode {mode_key} needs exactly 1 hint, got {hints}")
    if spec.hint_budget == 2 and len(hints) != 2:
        raise ValueError(f"mode {mode_key} needs exactly 2 hints, got {hints}")

    engine = _get_engine()          # reuse the process-local engine
    engine.reset()                   # clean slate -> no state leakage
    engine.set_mode(mode_key)        # lock the domain for the whole game
    engine.set_target(target)        # scope the 2-hint residual minimax
    for h in hints:
        engine.add_hint(h)

    turns = 0
    guesses: list[str] = [] if trace else []
    while True:
        turns += 1
        strat, _ = engine.get_suggestions(is_hard_mode=spec.hard)
        if not strat:
            return (target, -1, guesses)
        guess = strat[0]["word"]
        if trace:
            guesses.append(guess)
        if guess == target:
            return (target, turns, guesses)
        pattern = engine.calculate_pattern(guess, target)
        engine.update_state(guess, pattern)
        if turns >= 6:
            return (target, 7, guesses)


def play_mode(
    target: str,
    mode_key: str,
    hint_letters: Iterable[str] | None = None,
) -> tuple[str, int]:
    """Play one game in the locked domain ``mode_key``.

    Args:
        target: the secret answer (any case).
        mode_key: one of the six domain keys.
        hint_letters: for hinted modes, the EXACT letters to apply up front
            (must be a valid NYT hint set drawn from ``target``). Ignored
            for 0-hint modes; for 1-hint modes exactly one letter is used,
            for 2-hint modes both vowel and consonant are used.

    Returns:
        (word, -1)   -- no suggestions (shouldn't happen)
        (word, 1..6) -- solved in that many turns (win)
        (word, 7)    -- exhausted the 6 guesses without solving (loss)
    """
    word, turns, _ = _play_core(target, mode_key, hint_letters)
    return (word, turns)


def play_mode_trace(
    target: str,
    mode_key: str,
    hint_letters: Iterable[str] | None = None,
) -> tuple[str, int, list[str]]:
    """Like :func:`play_mode` but also returns the ordered list of guessed
    words. Used by the exhaustive enumeration report so the human can see the
    exact solve path for every (word, domain, hint) triple.
    """
    return _play_core(target, mode_key, hint_letters, trace=True)


def play_one_game(
    target: str,
    is_hard: bool = False,
    hints: bool = False,
    hint_letters: "list[str] | None" = None,
) -> tuple[str, int]:
    """Back-compat shim around :func:`play_mode`.

    ``hints=True`` -> the 2-hint domain (auto first-vowel x first-consonant
    pair, or the explicit ``hint_letters`` when given). ``hints=False`` -> the
    0-hint domain. ``hint_letters`` of length 1 -> 1-hint domain; length 2 ->
    2-hint domain.
    """
    target = target.lower().strip()
    if hint_letters:
        letters = list(dict.fromkeys(c.lower() for c in hint_letters))
        if len(letters) == 1:
            mode_key = "hard_1" if is_hard else "normal_1"
        elif len(letters) == 2:
            mode_key = "hard_2" if is_hard else "normal_2"
        else:
            raise ValueError("hint_letters must be length 1 or 2")
        return play_mode(target, mode_key, hint_letters=letters)
    if hints:
        # Reproduce the original auto-hint behavior: reveal the secret's
        # first vowel AND first consonant (one of each), as the NYT button
        # would. For the handful of all-consonant answers (e.g. 'crypt')
        # there is no vowel, so only one hint letter exists -> the 1-hint
        # domain. Map to whichever domain the available letters support.
        vs = [c for c in target if c in VOWELS]
        cs = [c for c in target if c in CONSONANTS]
        auto = ([vs[0]] if vs else []) + ([cs[0]] if cs else [])
        if len(auto) == 2:
            mode_key = "hard_2" if is_hard else "normal_2"
        elif len(auto) == 1:
            mode_key = "hard_1" if is_hard else "normal_1"
        else:
            mode_key = "hard_0" if is_hard else "normal_0"
        return play_mode(target, mode_key, hint_letters=auto)
    mode_key = "hard_0" if is_hard else "normal_0"
    return play_mode(target, mode_key)
