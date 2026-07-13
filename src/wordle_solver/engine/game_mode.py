"""Game-flow controller for the six locked Wordle domains.

The UI exposes only two controls *before the first guess*:
  * a Normal/Hard toggle, and
  * hint entry (0, 1, or 2 hint letters).
After turn 1 these switches are locked. It is THIS module's job to
translate that input into one of the six locked domains
(Normal/Hard x 0/1/2 hints) -- i.e. the backend *establishes the mode*
from the user's Normal/Hard choice and the number of hints actually
taken.

Strict separation is enforced by routing every engine call through the
ModeSpec selected by ``(hard, hint_count)``; editing one domain's
flags/data cannot affect another.

NYT hint rule (enforced here, not in the UI): a hint is one letter of the
secret; at most two hints; never two vowels and never two consonants
(always one vowel + one consonant when two are taken).
"""

from __future__ import annotations

from typing import Optional

from .modes import MODE_REGISTRY, VOWELS, CONSONANTS, get_spec

MAX_HINTS = 2  # NYT rule cap


class FlowError(Exception):
    """Raised when a flow rule is violated.

    ``code`` is one of: MODE_LOCKED | GAME_OVER | HINT_RULE | NON_LETTER.
    The web layer maps these to 409 (MODE_LOCKED/GAME_OVER) or 400
    (HINT_RULE/NON_LETTER) and attaches a loud, human message.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class GameMode:
    """Owns the flow: Normal/Hard toggle + hint entry, locked after turn 1."""

    def __init__(self) -> None:
        self.pending_hard = False
        self.hinted_letters = set()
        self.turn = 1
        self._over = False
        self._won = False
        self._mode_locked = False  # becomes True right after the first guess

    # ── derived domain ──────────────────────────────────────────
    @property
    def hard(self) -> bool:
        return self.pending_hard

    @property
    def hint_budget(self) -> int:
        """The MAX number of hints allowed (the NYT cap, always 2)."""
        return MAX_HINTS

    @property
    def hint_count(self) -> int:
        """How many hints have actually been taken so far (0/1/2)."""
        return len(self.hinted_letters)

    @property
    def mode_key(self) -> str:
        """The locked domain, derived from (hard, hint count)."""
        return ("hard" if self.pending_hard else "normal") + "_" + str(self.hint_count)

    @property
    def spec(self):
        return get_spec(self.mode_key)

    @property
    def mode_locked(self) -> bool:
        """True once the first guess is submitted -- switches are disabled."""
        return self._mode_locked

    @property
    def over(self) -> bool:
        return self._over

    @property
    def won(self) -> bool:
        return self._won

    # ── Normal/Hard toggle (turn 1 only) ────────────────────────
    def toggle_hard(self, on: bool) -> None:
        if self._mode_locked:
            raise FlowError("MODE_LOCKED", "Mode is locked after the first guess.")
        if self._over:
            raise FlowError("GAME_OVER", "Game is over.")
        self.pending_hard = bool(on)

    # ── hint entry (turn 1 only) ────────────────────────────────
    def can_add_hint(self, letter: str) -> tuple[bool, str]:
        """Validate a proposed hint WITHOUT mutating state.

        Reasons: 'ok' | 'NON_LETTER' | 'MODE_LOCKED' | 'GAME_OVER' |
        'DUP' | 'FULL' (>= 2 hints already) | 'TWO_VOWELS' | 'TWO_CONS'.
        """
        letter = (letter or "").strip().lower()
        if not (isinstance(letter, str) and len(letter) == 1 and letter.isalpha()):
            return False, "NON_LETTER"
        if self._mode_locked:
            return False, "MODE_LOCKED"
        if self._over:
            return False, "GAME_OVER"
        if letter in self.hinted_letters:
            return False, "DUP"
        if len(self.hinted_letters) >= MAX_HINTS:
            return False, "FULL"
        if letter in VOWELS and sum(1 for c in self.hinted_letters if c in VOWELS) >= 1:
            return False, "TWO_VOWELS"
        if letter in CONSONANTS and sum(1 for c in self.hinted_letters if c in CONSONANTS) >= 1:
            return False, "TWO_CONS"
        return True, "ok"

    def add_hint(self, letter: str) -> None:
        ok, reason = self.can_add_hint(letter)
        if not ok:
            if reason == "MODE_LOCKED":
                raise FlowError("MODE_LOCKED", "Hints are locked after the first guess.")
            if reason == "GAME_OVER":
                raise FlowError("GAME_OVER", "Game is over.")
            if reason == "DUP":
                raise FlowError("HINT_RULE", f"Hint '{letter.upper()}' already logged.")
            if reason == "FULL":
                raise FlowError("HINT_RULE",
                                "Only two hint letters are allowed (NYT: 1 vowel + 1 consonant).")
            if reason == "TWO_VOWELS":
                raise FlowError("HINT_RULE", "Only one vowel hint is allowed.")
            if reason == "TWO_CONS":
                raise FlowError("HINT_RULE", "Only one consonant hint is allowed.")
            if reason == "NON_LETTER":
                raise FlowError("NON_LETTER",
                                f"'{letter.upper() or letter}' is not a single A–Z letter.")
            raise FlowError("HINT_RULE", "Invalid hint letter.")
        self.hinted_letters.add(letter.lower())

    # ── guess submit: advances turn + ends the game at turn 6 ──
    def on_submit(self, solved: bool) -> None:
        """Call after a guess is accepted. Locks the mode after turn 1."""
        self._mode_locked = True
        if solved:
            self._won = True
            self._over = True
        else:
            self.turn += 1
            if self.turn > 6:
                self._over = True

    def reset(self) -> None:
        self.__init__()
