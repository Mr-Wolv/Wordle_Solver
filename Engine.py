import numpy as np
import pandas as pd


class WordleEngine:
    def __init__(
        self,
        words_path="scientific_word_data.csv",
        matrix_path="wordle_full_matrix.npy",
    ):
        self.df = pd.read_csv(words_path)
        self.all_words = self.df["word"].tolist()

        # Load and normalize probabilities
        probs = self.df["probability"].values.copy()
        probs = np.maximum(probs, 1e-10) # type: ignore
        self.global_probs = probs / probs.sum()

        # Load pattern matrix
        self.matrix = np.load(matrix_path)

        # Game State
        self.possible_indices = np.arange(len(self.all_words))
        self.turn = 1

    def get_suggestions(self):
        """Returns top 10 strategic moves and top 10 candidates."""
        current_weights = self.global_probs[self.possible_indices]
        current_weights /= current_weights.sum()

        # We look at the matrix for ALL words against CURRENT possible answers
        pool_matrix = self.matrix[:, self.possible_indices]

        results = []
        for i in range(len(self.all_words)):
            patterns = pool_matrix[i]
            # Fast entropy calculation
            counts = np.bincount(patterns, weights=current_weights, minlength=243)
            nz = counts[counts > 0]
            entropy = -np.sum(nz * np.log2(nz))

            win_prob = 0
            is_candidate = i in self.possible_indices
            if is_candidate:
                pool_loc = np.where(self.possible_indices == i)[0][0]
                win_prob = current_weights[pool_loc]

            # Improved scoring logic (Pesimistic early, Balanced mid, Aggressive late)
            if self.turn <= 2:
                score = entropy
            elif 3 <= self.turn <= 4 and len(self.possible_indices) > 2:
                score = entropy + (0.05 * win_prob)
            elif len(self.possible_indices) <= 2:
                score = entropy + (5.0 * win_prob)
            else:
                score = entropy + (10.0 * win_prob)

            results.append(
                {
                    "word": self.all_words[i],
                    "score": score,
                    "win_prob": win_prob,
                    "is_candidate": is_candidate,
                }
            )

        top_strategic = sorted(results, key=lambda x: x["score"], reverse=True)[:10]
        top_candidates = sorted(
            [r for r in results if r["is_candidate"]],
            key=lambda x: x["win_prob"],
            reverse=True,
        )[:10]

        return top_strategic, top_candidates

    def update_state(self, guess, pattern_int):
        """Filters the pool based on the user's input."""
        guess_idx = self.all_words.index(guess)
        actual_patterns = self.matrix[guess_idx, self.possible_indices]
        self.possible_indices = self.possible_indices[actual_patterns == pattern_int]
        self.turn += 1

    def reset(self):
        self.possible_indices = np.arange(len(self.all_words))
        self.turn = 1
