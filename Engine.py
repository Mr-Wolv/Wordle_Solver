import numpy as np
import pandas as pd
from utils import resource_path


class WordleEngine:
    """Entropy-driven Wordle solver with worst-case (minimax) awareness.

    Performance features:
      - O(1) word-to-index dict
      - O(1) boolean possible_mask for membership checks
      - Precomputed full_weights array (eliminates np.where in hot loop)
      - Memory-mapped matrix (shared across test worker processes)

    Algorithm:
      - Weighted Shannon entropy for expected information gain
      - Worst-case (max bucket size) penalty to avoid landmine clusters
      - Phase-aware: early (info-gathering), mid (balanced), late (aggressive)
      - **Hard mode** uses the same full-dictionary search space as normal mode
        (real Wordle hard mode allows any valid guess that respects clues).
    """

    # ── Scoring Constants ──────────────────────────────────────────────
    ENDGAME_WIN_BONUS = 10.0
    WIN_BONUS_WEIGHT = 5.0

    # Standard mode
    STD_EARLY_WC_PENALTY = 0.3
    STD_BASE_PENALTY = 0.5
    STD_PENALTY_PER_TURN = 0.4
    STD_MAX_PENALTY = 3.0
    STD_SMALL_POOL = 5

    # Hard mode: stronger worst-case avoidance (can't use burner words)
    HARD_EARLY_WC_PENALTY = 1.2
    HARD_BASE_PENALTY = 1.0
    HARD_PENALTY_PER_TURN = 0.5
    HARD_MAX_PENALTY = 4.0
    HARD_SMALL_POOL = 10

    def __init__(
        self,
        words_path: str = resource_path("scientific_word_data.csv"),
        matrix_path: str = resource_path("wordle_full_matrix.npy"),
    ) -> None:
        self.df = pd.read_csv(words_path)
        self.all_words: list[str] = self.df["word"].tolist()

        # O(1) word → index lookup
        self.word_to_idx: dict[str, int] = {
            word: i for i, word in enumerate(self.all_words)
        }

        # Normalise global word probabilities
        probs = self.df["probability"].values.copy()
        probs = np.maximum(probs, 1e-10)
        self.global_probs: np.ndarray = probs / probs.sum()

        # Memory-mapped so multiple test processes share the same pages
        self.matrix: np.ndarray = np.load(matrix_path, mmap_mode="r")

        n_words = len(self.all_words)
        self.possible_indices: np.ndarray = np.arange(n_words)
        self.possible_mask: np.ndarray = np.ones(n_words, dtype=bool)

        # Pre-allocated full-size weight array (0 for impossible words)
        self.full_weights: np.ndarray = np.zeros(n_words, dtype=np.float64)

        self.turn: int = 1

    # ── Public API ─────────────────────────────────────────────────────

    def get_suggestions(
        self, is_hard_mode: bool = False
    ) -> tuple[list[dict], list[dict]]:
        """Return (top-10 strategic suggestions, top-10 candidate solutions).

        The scoring function combines:
          - Shannon entropy (expected information gain)
          - Worst-case penalty (fraction in largest pattern bucket)
          - Win-probability bonus (direct solve chance)

        In **hard mode** the full dictionary is used as the search space
        (real Wordle hard mode allows any valid guess that respects revealed
        clues).  The stronger worst-case penalty naturally biases towards
        candidate words when they are equally informative.
        """
        pool_size = len(self.possible_indices)
        if pool_size == 0:
            return [], []

        # Normalise weights for current candidate pool
        current_weights = self.global_probs[self.possible_indices]
        current_weights /= current_weights.sum()

        # Update the full-size weight array (0 for impossible words)
        self.full_weights.fill(0.0)
        self.full_weights[self.possible_indices] = current_weights

        pool_matrix = self.matrix[:, self.possible_indices]

        # Scoring constants for this mode
        early_penalty, max_penalty, search_pool = self._mode_constants(is_hard_mode)
        turn_penalty = self._worst_case_penalty(is_hard_mode)

        # In hard mode: only search the full dictionary when the pool is small
        # enough to need cluster-breaking non-candidate words.  When the pool
        # is large, restrict to candidates for speed (the additional words
        # don't help much when the answer space is still broad).
        if is_hard_mode and pool_size <= search_pool:
            search_indices = np.arange(len(self.all_words))
        else:
            search_indices = self.possible_indices if is_hard_mode else np.arange(len(self.all_words))

        results: list[dict] = []
        for i in search_indices:
            patterns = pool_matrix[i]
            counts = np.bincount(
                patterns, weights=current_weights, minlength=243
            )
            nz = counts[counts > 0]
            entropy = -float(np.sum(nz * np.log2(nz)))

            win_prob = float(self.full_weights[i])
            worst_case = float(counts.max())  # fraction (0-1) in worst bucket

            # ── Phase-aware scoring ──
            if pool_size <= 2:
                score = entropy + self.ENDGAME_WIN_BONUS * win_prob
            elif self.turn <= 2:
                score = entropy - early_penalty * worst_case
            elif pool_size <= search_pool or (
                self.turn >= 4 and worst_case > 0.35
            ):
                # Danger zone: aggressive worst-case + balanced win_prob
                score = (
                    entropy
                    - max_penalty * worst_case
                    + 0.5 * win_prob
                )
            else:
                score = (
                    entropy
                    - turn_penalty * worst_case
                    + self.WIN_BONUS_WEIGHT * win_prob
                )

            results.append(
                {
                    "word": self.all_words[i],
                    "score": score,
                    "win_prob": win_prob,
                    "is_candidate": bool(self.possible_mask[i]),
                }
            )

        top_strategic = sorted(results, key=lambda x: x["score"], reverse=True)[:10]

        top_candidates = sorted(
            [r for r in results if r["is_candidate"]],
            key=lambda x: x["win_prob"],
            reverse=True,
        )[:10]

        return top_strategic, top_candidates

    def update_state(self, guess: str, pattern_int: int) -> bool:
        """Filter the candidate pool using observed feedback."""
        guess_idx = self.word_to_idx[guess]  # O(1)
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
        """Reset the engine to initial state."""
        n_words = len(self.all_words)
        self.possible_indices = np.arange(n_words)
        self.possible_mask = np.ones(n_words, dtype=bool)
        self.turn = 1

    def calculate_pattern(self, guess: str, secret: str) -> int:
        """Compute Wordle pattern as a base-3 integer (0-242).

        0 = grey, 1 = yellow, 2 = green.
        """
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

    def _mode_constants(
        self, is_hard_mode: bool
    ) -> tuple[float, float, int]:
        """Return (early_penalty, max_penalty, small_pool) for the mode."""
        if is_hard_mode:
            return (
                self.HARD_EARLY_WC_PENALTY,
                self.HARD_MAX_PENALTY,
                self.HARD_SMALL_POOL,
            )
        return (
            self.STD_EARLY_WC_PENALTY,
            self.STD_MAX_PENALTY,
            self.STD_SMALL_POOL,
        )

    def _worst_case_penalty(self, is_hard_mode: bool) -> float:
        """Penalty weight that grows with turn number."""
        if is_hard_mode:
            return min(
                self.HARD_MAX_PENALTY,
                self.HARD_BASE_PENALTY + self.turn * self.HARD_PENALTY_PER_TURN,
            )
        return min(
            self.STD_MAX_PENALTY,
            self.STD_BASE_PENALTY + self.turn * self.STD_PENALTY_PER_TURN,
        )
