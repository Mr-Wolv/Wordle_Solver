import numpy as np
import pandas as pd


# 1. Load the pattern engine functions we defined earlier
def get_wordle_pattern(guess, secret):
    pattern = [0] * 5
    secret_list = list(secret)
    guess_list = list(guess)
    for i in range(5):
        if guess_list[i] == secret_list[i]:
            pattern[i] = 2
            secret_list[i] = None
            guess_list[i] = None
    for i in range(5):
        if guess_list[i] is not None:
            if guess_list[i] in secret_list:
                pattern[i] = 1
                secret_list[secret_list.index(guess_list[i])] = None
    return tuple(pattern)


def pattern_to_int(pattern):
    return sum(p * (3**i) for i, p in enumerate(pattern))


# 2. The Builder Logic
def build_full_matrix():
    df = pd.read_csv("scientific_word_data.csv")
    all_words = df["word"].tolist()
    n = len(all_words)

    # Use uint8 to keep the file size manageable (approx 168MB)
    matrix = np.zeros((n, n), dtype=np.uint8)

    print(f"Baking FULL matrix: {n} x {n}...")

    for i, guess in enumerate(all_words):
        for j, secret in enumerate(all_words):
            # Using the same pattern logic from before
            p_tuple = get_wordle_pattern(guess, secret)
            matrix[i, j] = pattern_to_int(p_tuple)

        if i % 500 == 0:
            print(f"Progress: {i}/{n} words processed")

    np.save("wordle_full_matrix.npy", matrix)
    print("Full matrix saved as 'wordle_full_matrix.npy'")


if __name__ == "__main__":
    build_full_matrix()
