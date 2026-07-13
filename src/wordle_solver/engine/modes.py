"""The six Wordle domains as frozen, first-class registry entries.

Design goal (see request): the 6 playable domains are STRICTLY SEPARATE.
Editing one domain's configuration/data MUST NOT affect the others. We
make that literal: each domain is a frozen :class:`ModeSpec` carrying its
own identity, scoring parameters, and an explicit, self-contained
*specialist partition* that maps the engine's internal specialist trees to
domain usage — so no specialist is ever silently shared across domains,
and adding/removing one domain's data cannot change another's dispatch.

The six domains:
    M1  normal  0 hints
    M2  hard    0 hints
    M3  normal  1 hint
    M4  hard    1 hint
    M5  normal  2 hints
    M6  hard    2 hints

Each spec declares, by name and boolean flag, exactly which of the
precomputed specialist tables it is allowed to consult. The engine reads
ONLY its active domain's spec — it never reaches into a sibling domain.
Because the flags are per-domain and the defaults are copied (not aliased),
mutating one spec cannot touch another.

The HINT RULE (fixed, not free-form): exactly ONE vowel AND ONE consonant,
both drawn from the secret's own letters. Legal hint counts are therefore
0 (none), 1 (one vowel OR one consonant), or 2 (one vowel + one consonant).
Two vowels, two consonants, or >2 are illegal at the engine-flow level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Mapping


# ── hint-rule constants (the NYT button: 1 consonant + 1 vowel) ──
VOWELS = frozenset("aeiou")
CONSONANTS = frozenset("bcdfghjklmnpqrstvwxyz")
MAX_HINTS = 2  # exactly one consonant AND one vowel


@dataclass(frozen=True)
class ModeSpec:
    """A single, isolated Wordle domain.

    Attributes:
        key: canonical identifier, one of the six names below.
        hard: whether this domain is HARD (NYT hard-mode rule enforced).
        hint_budget: max hints allowed (0, 1, or 2).
        # Per-domain scoring parameters (copied from engine tunables so a
        # change to one domain's numbers cannot leak into another):
        std_early, std_turn, hard_early, hard_base, hard_per_turn,
        hard_max, win_bonus, endgame_win: scoring knobs.
        # Self-contained specialist partition: exactly which specialist
        # tables this domain may consult. The engine dispatches ONLY through
        # these, so domains never share a specialist implicit in code.
        use_nohint_specialist:   # hard no-hint optimal-shredder tree
        use_2hint_specialist:     # residual_optimal (2-hint) tree
        use_1hint_specialist:     # residual_optimal_1hint tree
        use_t1_h_override:        # turn-1 'h' family-safe opening
        use_nohint_rescue:        # small-pool optimal-minimax rescue
    """

    key: str
    hard: bool
    hint_budget: int
    # scoring params (per-domain copies)
    std_early: float
    std_turn: float
    hard_early: float
    hard_base: float
    hard_per_turn: float
    hard_max: float
    win_bonus: float
    endgame_win: float
    # specialist partition (self-contained, per domain)
    use_nohint_specialist: bool
    use_2hint_specialist: bool
    use_1hint_specialist: bool
    use_t1_h_override: bool
    use_nohint_rescue: bool
    # Hinted small-pool optimal-minimax rescue: closes the endgame residuals
    # greedy cannot (it can guess the wrong word in a 2-word pool and blow the
    # 6-turn cap). Off by default; only the hinted domains that need it opt in
    # so the already-100% domains are never touched (strict isolation).
    use_hinted_rescue: bool
    # 2-hint turn-1 worst-case splitter: opens with the guess that minimises the
    # largest remaining bucket over the hinted pool, breaking tight sibling
    # clusters greedy's entropy opening would strand. Off by default.
    use_2hint_split_opening: bool

    # ── derived helpers (pure, no engine dependency) ──
    @property
    def hint_count(self) -> int:
        return self.hint_budget

    @property
    def is_hard(self) -> bool:
        return self.hard

    @property
    def is_hinted(self) -> bool:
        return self.hint_budget > 0

    def allows_hint(self, current_count: int) -> bool:
        """Forward-only flow: a hint may be added iff it won't exceed budget.

        Permits the 0->1, 1->2, AND 0->2 jumps (the caller makes two adds
        before guessing to realize the jump), and forbids any reverse/
        removal (once current_count is at budget, nothing more is allowed).
        """
        return 0 <= current_count < self.hint_budget

    def specialist_partition(self) -> Mapping[str, bool]:
        return {
            "nohint_specialist": self.use_nohint_specialist,
            "2hint_specialist": self.use_2hint_specialist,
            "1hint_specialist": self.use_1hint_specialist,
            "t1_h_override": self.use_t1_h_override,
            "nohint_rescue": self.use_nohint_rescue,
        }


# Engine tunables (the proven 100% values from engine.py). Copied here so
# each domain binds its OWN copy — editing engine.py's module-level
# constants later cannot silently retune a domain that doesn't reference
# them. When a domain genuinely shares a value, it still holds its own
# literal copy (no aliasing).
_STD_EARLY = 3.1
_STD_TURN = 3.0
_HARD_EARLY = 4.5
_HARD_BASE = 3.8
_HARD_PER_TURN = 1.7
_HARD_MAX = 10.0
_WIN_BONUS = 0.3
_ENDGAME_WIN = 1.5

# ── the six frozen domains ──────────────────────────────────────
# Specialist partition rationale (each domain declares its OWN slice of the
# shared offline-built tables, so nothing is implicit):
#   M1 normal/0  : greedy + no-hint rescue (closes normal residuals)
#   M2 hard/0    : greedy + no-hint rescue + HARD no-hint shredder tree
#   M3 normal/1  : greedy + 1-hint specialist (the 1hint tree serves both
#                   modes; built hard-legal so it is also normal-legal)
#   M4 hard/1    : greedy + 1-hint specialist
#   M5 normal/2  : PURE GREEDY (the 2-hint tree + t1_h override are
#                   HARD-only in the proven solver; enabling them here would
#                   change behaviour and risk the 100% — normal 2-hint already
#                   hits 100% via greedy)
#   M6 hard/2    : greedy + 2-hint specialist + t1_h override (h-word)
MODE_SPECS: tuple[ModeSpec, ...] = (
    ModeSpec("normal_0", False, 0,
             _STD_EARLY, _STD_TURN, _HARD_EARLY, _HARD_BASE,
             _HARD_PER_TURN, _HARD_MAX, _WIN_BONUS, _ENDGAME_WIN,
             use_nohint_specialist=False, use_2hint_specialist=False,
             use_1hint_specialist=False, use_t1_h_override=False,
             use_nohint_rescue=True, use_hinted_rescue=False,
             use_2hint_split_opening=False),
    ModeSpec("hard_0", True, 0,
             _STD_EARLY, _STD_TURN, _HARD_EARLY, _HARD_BASE,
             _HARD_PER_TURN, _HARD_MAX, _WIN_BONUS, _ENDGAME_WIN,
             use_nohint_specialist=True, use_2hint_specialist=False,
             use_1hint_specialist=False, use_t1_h_override=False,
             use_nohint_rescue=True, use_hinted_rescue=False,
             use_2hint_split_opening=False),
    ModeSpec("normal_1", False, 1,
             _STD_EARLY, _STD_TURN, _HARD_EARLY, _HARD_BASE,
             _HARD_PER_TURN, _HARD_MAX, _WIN_BONUS, _ENDGAME_WIN,
             use_nohint_specialist=False, use_2hint_specialist=False,
             use_1hint_specialist=True, use_t1_h_override=False,
             use_nohint_rescue=False, use_hinted_rescue=False,
             use_2hint_split_opening=False),
    ModeSpec("hard_1", True, 1,
             _STD_EARLY, _STD_TURN, _HARD_EARLY, _HARD_BASE,
             _HARD_PER_TURN, _HARD_MAX, _WIN_BONUS, _ENDGAME_WIN,
             use_nohint_specialist=False, use_2hint_specialist=False,
             use_1hint_specialist=True, use_t1_h_override=False,
             use_nohint_rescue=False, use_hinted_rescue=False,
             use_2hint_split_opening=False),
    # normal_2: enable the hinted small-pool optimal-minimax rescue (greedy
    # alone leaves 7 words at 7 turns in a 2-word endgame, caught by the full
    # 2315-word gate). The rescue only fires for pools it can PROVE solvable in
    # <= remaining moves, so it cannot regress; it stays off for all other
    # domains to preserve their 100% (strict isolation).
    ModeSpec("normal_2", False, 2,
             _STD_EARLY, _STD_TURN, _HARD_EARLY, _HARD_BASE,
             _HARD_PER_TURN, _HARD_MAX, _WIN_BONUS, _ENDGAME_WIN,
             use_nohint_specialist=False, use_2hint_specialist=True,
             use_1hint_specialist=False, use_t1_h_override=False,
             use_nohint_rescue=False, use_hinted_rescue=True,
             use_2hint_split_opening=True),
    ModeSpec("hard_2", True, 2,
             _STD_EARLY, _STD_TURN, _HARD_EARLY, _HARD_BASE,
             _HARD_PER_TURN, _HARD_MAX, _WIN_BONUS, _ENDGAME_WIN,
             use_nohint_specialist=False, use_2hint_specialist=True,
             use_1hint_specialist=False, use_t1_h_override=True,
             use_nohint_rescue=False, use_hinted_rescue=True,
             use_2hint_split_opening=True),
)

# The canonical order the request enumerates domains in.
MODE_ORDER: tuple[str, ...] = (
    "normal_0", "hard_0", "normal_1", "hard_1", "normal_2", "hard_2",
)

# Domain index ⇄ spec registry (immutable mapping).
MODE_REGISTRY: dict[str, ModeSpec] = {m.key: m for m in MODE_SPECS}


def get_spec(key: str) -> ModeSpec:
    return MODE_REGISTRY[key]


def all_specs() -> tuple[ModeSpec, ...]:
    return MODE_SPECS


def hint_composition_ok(n_vowels: int, n_consonants: int) -> bool:
    """The fixed NYT hint rule: at most one vowel AND one consonant.

    Legal final states:
        (0,0) -> 0 hints
        (1,0) -> 1 hint (vowel-only)
        (0,1) -> 1 hint (consonant-only)
        (1,1) -> 2 hints
    Illegal: (2,*) (two vowels), (*,2) (two consonants), or total > 2.
    """
    return (n_vowels <= 1 and n_consonants <= 1
            and (n_vowels + n_consonants) <= MAX_HINTS)
