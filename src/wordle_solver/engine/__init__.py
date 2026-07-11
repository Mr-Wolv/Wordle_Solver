"""Wordle solver engine: data, scoring, controller, self-play."""

from .lexicon import Lexicon, PatternMatrix
from .scoring import score_guesses
from .engine import (
    WordleEngine,
    STD_EARLY_WC_PENALTY, STD_TURN_PENALTY, HARD_EARLY_WC_PENALTY,
    HARD_BASE_PENALTY, HARD_PENALTY_PER_TURN, HARD_MAX_PENALTY,
    WIN_BONUS_WEIGHT, ENDGAME_WIN_BONUS,
)
from ..utils import resource_path
from .engine import (
    VOWELS, CONSONANTS, MAX_HINTS, _hint_counts,
)
from .game import play_one_game
from .patterns import (
    calculate_pattern,
    pattern_int_to_tuple,
    minimax_best,
    build_optimal_table,
)

__all__ = [
    "Lexicon", "PatternMatrix", "score_guesses", "WordleEngine", "play_one_game",
    "calculate_pattern", "pattern_int_to_tuple", "minimax_best", "build_optimal_table",
    "STD_EARLY_WC_PENALTY", "STD_TURN_PENALTY", "HARD_EARLY_WC_PENALTY",
    "HARD_BASE_PENALTY", "HARD_PENALTY_PER_TURN", "HARD_MAX_PENALTY",
    "WIN_BONUS_WEIGHT", "ENDGAME_WIN_BONUS",
]
