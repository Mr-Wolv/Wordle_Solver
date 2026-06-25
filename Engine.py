import numpy as np
import pandas as pd
from utils import resource_path


class WordleEngine:
    """Entropy-driven Wordle solver optimized for average turns.

    Performance features:
      - O(1) word-to-index dict
      - O(1) boolean possible_mask for membership checks
      - Precomputed full_weights array (eliminates np.where in hot loop)
      - Memory-mapped matrix (shared across test worker processes)

    Algorithm:
      - Weighted Shannon entropy for expected information gain
      - Light worst-case penalty to avoid catastrophic splits
      - Phase-aware scoring: early (pure information-gathering), mid/late (balanced)
      - Minimax endgame for pool ≤ 5 (guarantee solve when very close)
      - **Hard mode** uses the same full-dictionary search space as normal mode.
    """

    # ── Scoring Constants ──────────────────────────────────────────────
    ENDGAME_WIN_BONUS = 10.0
    WIN_BONUS_WEIGHT = 1.0       # minimal win-prob bias; prefer informative guesses

    # Standard mode — near-pure entropy for optimal average turns
    STD_EARLY_WC_PENALTY = 0.0       # pure entropy on turns 1-2
    STD_BASE_PENALTY = 0.0
    STD_PENALTY_PER_TURN = 0.2       # mild penalty that grows with turns
    STD_MAX_PENALTY = 1.0

    # Hard mode — slightly more cautious due to constrained search space
    HARD_EARLY_WC_PENALTY = 0.4       # mild worst-case awareness on turns 1-2
    HARD_BASE_PENALTY = 0.5
    HARD_PENALTY_PER_TURN = 0.3
    HARD_MAX_PENALTY = 2.0

    # Class-level turn-1 cache
    _turn1_cache: dict[tuple, tuple[list[dict], list[dict]]] = {}

    def __init__(
        self,
        words_path: str = resource_path("scientific_word_data.csv"),
        matrix_path: str = resource_path("wordle_full_matrix.npy"),
    ) -> None:
        self.df = pd.read_csv(words_path)
        self.all_words: list[str] = self.df["word"].tolist()
        self.word_to_idx: dict[str, int] = {
            word: i for i, word in enumerate(self.all_words)
        }
        probs = self.df["probability"].values.copy()
        probs = np.maximum(probs, 1e-10)
        self.global_probs: np.ndarray = probs / probs.sum()
        self.matrix: np.ndarray = np.load(matrix_path, mmap_mode="r")
        n_words = len(self.all_words)
        self.possible_indices: np.ndarray = np.arange(n_words)
        self.possible_mask: np.ndarray = np.ones(n_words, dtype=bool)
        self.full_weights: np.ndarray = np.zeros(n_words, dtype=np.float64)
        self.turn: int = 1

    # ── First-turn cache ────────────────────────────────────────────

    def _first_turn(self, is_hard_mode: bool) -> tuple[list[dict], list[dict]]:
        key = (is_hard_mode,)
        if key in self._turn1_cache:
            return self._turn1_cache[key]

        is_hard = is_hard_mode
        pool_size = len(self.possible_indices)
        current_weights = self.global_probs.copy()
        current_weights /= current_weights.sum()
        self.full_weights.fill(0.0)
        self.full_weights[self.possible_indices] = current_weights
        pool_matrix = self.matrix[:, self.possible_indices]
        early_penalty = self._mode_constants(is_hard)
        turn_penalty = self._worst_case_penalty(is_hard)
        search_indices = np.arange(len(self.all_words))

        results = [
            self._score_word(
                i, pool_matrix[i], current_weights,
                pool_size, early_penalty, turn_penalty,
            )
            for i in search_indices
        ]

        top_strategic = sorted(results, key=lambda x: x["score"], reverse=True)[:10]
        top_candidates = sorted(
            [r for r in results if r["is_candidate"]],
            key=lambda x: x["win_prob"],
            reverse=True,
        )[:10]

        self._turn1_cache[key] = (top_strategic, top_candidates)
        return top_strategic, top_candidates

    # ── Public API ─────────────────────────────────────────────────────

    def get_suggestions(
        self, is_hard_mode: bool = False
    ) -> tuple[list[dict], list[dict]]:
        if self.turn == 1:
            return self._first_turn(is_hard_mode)

        pool_size = len(self.possible_indices)
        if pool_size == 0:
            return [], []

        current_weights = self.global_probs[self.possible_indices]
        current_weights /= current_weights.sum()

        self.full_weights.fill(0.0)
        self.full_weights[self.possible_indices] = current_weights

        pool_matrix = self.matrix[:, self.possible_indices]
        early_penalty = self._mode_constants(is_hard_mode)
        turn_penalty = self._worst_case_penalty(is_hard_mode)
        search_indices = np.arange(len(self.all_words))

        results = [
            self._score_word(
                i, pool_matrix[i], current_weights,
                pool_size, early_penalty, turn_penalty,
            )
            for i in search_indices
        ]

        top_strategic = sorted(results, key=lambda x: x["score"], reverse=True)[:10]
        top_candidates = sorted(
            [r for r in results if r["is_candidate"]],
            key=lambda x: x["win_prob"],
            reverse=True,
        )[:10]

        return top_strategic, top_candidates

    # ── State management ────────────────────────────────────────────────

    def update_state(self, guess: str, pattern_int: int) -> bool:
        guess_idx = self.word_to_idx[guess]
        actual_patterns = self.matrix[guess_idx, self.possible_indices]
        new_mask = actual_patterns == pattern_int
        new_indices = self.possible_indices[new_mask]

        if len(new_indices) == 0:
            print(
                "ERROR: No words match this pattern. "
                "Is the secret word in the dictionary?"
            )
            return False

        self.possible_indices = new_indices
        self.possible_mask = np.zeros(len(self.all_words), dtype=bool)
        self.possible_mask[new_indices] = True
        self.turn += 1
        return True

    def reset(self) -> None:
        n_words = len(self.all_words)
        self.possible_indices = np.arange(n_words)
        self.possible_mask = np.ones(n_words, dtype=bool)
        self.turn = 1

    def calculate_pattern(self, guess: str, secret: str) -> int:
        p = [0] * 5
        secret_list = list(secret)
        guess_list = list(guess)
        for i in range(5):
            if guess_list[i] == secret_list[i]:
                p[i] = 2
                secret_list[i] = None
                guess_list[i] = None
        for i in range(5):
            if guess_list[i] is not None and guess_list[i] in secret_list:
                p[i] = 1
                secret_list[secret_list.index(guess_list[i])] = None
        pattern_int = 0
        for i in range(5):
            pattern_int += p[i] * (3**i)
        return pattern_int

    # ── Scoring helpers ────────────────────────────────────────────────

    def _score_word(
        self,
        word_idx: int,
        patterns: np.ndarray,
        current_weights: np.ndarray,
        pool_size: int,
        early_penalty: float,
        turn_penalty: float,
    ) -> dict:
        counts = np.bincount(patterns, weights=current_weights, minlength=243)
        nz = counts[counts > 0]
        entropy = -float(np.sum(nz * np.log2(nz)))
        win_prob = float(self.full_weights[word_idx])
        worst_case = float(counts.max())

        # Phase-aware scoring — optimized for average turns, not worst-case
        if pool_size <= 2:
            score = entropy + self.ENDGAME_WIN_BONUS * win_prob
        elif pool_size <= 5:
            # Minimax endgame: guarantee the solve when close
            score = -100.0 * worst_case + 0.01 * entropy + win_prob
        elif self.turn <= 2:
            # Early game: maximize information gain
            score = entropy - early_penalty * worst_case
        else:
            # Mid-to-late game: balanced with win-prob bonus
            score = entropy - turn_penalty * worst_case + self.WIN_BONUS_WEIGHT * win_prob

        return {
            "word": self.all_words[word_idx],
            "score": score,
            "win_prob": win_prob,
            "is_candidate": bool(self.possible_mask[word_idx]),
        }

    def _mode_constants(self, is_hard_mode: bool) -> float:
        return self.HARD_EARLY_WC_PENALTY if is_hard_mode else self.STD_EARLY_WC_PENALTY

    def _worst_case_penalty(self, is_hard_mode: bool) -> float:
        if is_hard_mode:
            return min(
                self.HARD_MAX_PENALTY,
                self.HARD_BASE_PENALTY + self.turn * self.HARD_PENALTY_PER_TURN,
            )
        return min(
            self.STD_MAX_PENALTY,
            self.STD_BASE_PENALTY + self.turn * self.STD_PENALTY_PER_TURN,
        )
