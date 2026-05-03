import numpy as np
import pandas as pd
import sys
import os


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # type: ignore
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class WordleEngine:
    def __init__(
        self,
        words_path=resource_path("scientific_word_data.csv"),
        matrix_path=resource_path("wordle_full_matrix.npy"),
    ):
        self.df = pd.read_csv(words_path)
        self.all_words = self.df["word"].tolist()

        probs = self.df["probability"].values.copy()
        probs = np.maximum(probs, 1e-10)  # type: ignore
        self.global_probs = probs / probs.sum()

        self.matrix = np.load(matrix_path)

        self.possible_indices = np.arange(len(self.all_words))
        self.turn = 1

    def get_suggestions(self, is_hard_mode=False):
        """Returns top 10 moves. Respects Hard Mode if toggled."""
        current_weights = self.global_probs[self.possible_indices]
        current_weights /= current_weights.sum()

        # [LOGIC CHANGE] Define our search space
        if is_hard_mode:
            # In Hard Mode, we only calculate scores for words that are still possible answers
            search_indices = self.possible_indices
        else:
            # In Standard Mode, we test every word in the dictionary
            search_indices = np.arange(len(self.all_words))

        pool_matrix = self.matrix[:, self.possible_indices]

        results = []
        for i in search_indices:
            patterns = pool_matrix[i]
            counts = np.bincount(patterns, weights=current_weights, minlength=243)
            nz = counts[counts > 0]
            entropy = -np.sum(nz * np.log2(nz))

            win_prob = 0
            is_candidate = i in self.possible_indices
            if is_candidate:
                pool_loc = np.where(self.possible_indices == i)[0][0]
                win_prob = current_weights[pool_loc]

            # Improved scoring logic
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

        # Candidate list is always from possible_indices regardless of mode
        top_candidates = sorted(
            [r for r in results if r["is_candidate"]],
            key=lambda x: x["win_prob"],
            reverse=True,
        )[:10]

        return top_strategic, top_candidates

    def update_state(self, guess, pattern_int):
        guess_idx = self.all_words.index(guess)
        actual_patterns = self.matrix[guess_idx, self.possible_indices]

        new_indices = self.possible_indices[actual_patterns == pattern_int]

        if len(new_indices) == 0:
            # Instead of crashing, raise a custom error or return False
            print("ERROR: No words match this pattern. Is the secret word in the dictionary?")
            return False 

        self.possible_indices = new_indices
        self.turn += 1
        return True

    def reset(self):
        self.possible_indices = np.arange(len(self.all_words))
        self.turn = 1

    def calculate_pattern(self, guess, secret):
        """Calculates the Wordle pattern (0-242) for a guess against a secret word."""
        p = [0] * 5
        secret_list = list(secret)
        guess_list = list(guess)

        # First pass: Find Greens
        for i in range(5):
            if guess_list[i] == secret_list[i]:
                p[i] = 2
                secret_list[i] = None
                guess_list[i] = None

        # Second pass: Find Yellows
        for i in range(5):
            if guess_list[i] is not None and guess_list[i] in secret_list:
                p[i] = 1
                secret_list[secret_list.index(guess_list[i])] = None

        # Convert base-3 to integer 0-242
        pattern_int = 0
        for i in range(5):
            pattern_int += p[i] * (3**i)
        return pattern_int


# if __name__ == "__main__":
#     engine = WordleEngine()
#     secret_word = "Puffy"  # Change this to test different words

#     print(f"Target Word: {secret_word.upper()}")

#     while len(engine.possible_indices) > 0:
#         # 1. Get the suggestion
#         strat, candidates = engine.get_suggestions(is_hard_mode=True)
#         best_guess = strat[0]["word"]

#         # 2. Calculate the pattern
#         pattern = engine.calculate_pattern(best_guess, secret_word)

#         # 3. Try to update the state
#         success = engine.update_state(best_guess, pattern)

#         # [CRITICAL] If update_state returns False, KILL THE LOOP
#         if not success:
#             print(
#                 f"Turn {engine.turn}: Guessed '{best_guess}' -> ❌ NO MATCHES FOUND. EXITING."
#             )
#             break

#         print(
#             f"Turn {engine.turn-1}: Guessed '{best_guess}', Pool size: {len(engine.possible_indices)}"
#         )

#         if best_guess == secret_word:
#             print("✅ Perfect Match!")
#             break
