from wordfreq import zipf_frequency  # zipf_frequency gives a nice 0-8 scale
import pandas as pd

# 1. Load the universe from Kaggle files
solutions = pd.read_csv("valid_solutions.csv")["word"].tolist()
guesses = pd.read_csv("valid_guesses.csv")["word"].tolist()
all_words = list(set(solutions + guesses))

# 2. Get Real World Zipf Scores
# Zipf score is the log10 frequency per billion words.
# 'the' is ~7.5, 'crane' is ~3.5, obscure words are ~1.0
word_data = []
for word in all_words:
    score = zipf_frequency(word, "en")
    word_data.append({"word": word, "zipf": score})

df = pd.DataFrame(word_data)

# 3. Convert Zipf to Linear Weight
# Since Zipf is logarithmic, we convert it back to a linear scale
# so the Entropy math (which expects probabilities) works correctly.
df["weight"] = 10 ** df["zipf"]
df["probability"] = df["weight"] / df["weight"].sum()

# 4. Sort and Save
df = df.sort_values(by="probability", ascending=False)
df.to_csv("scientific_word_data.csv", index=False)
