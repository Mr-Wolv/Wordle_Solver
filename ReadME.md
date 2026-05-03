# Wordle Solver

A Python-based Wordle assistant that combines probability-weighted candidate selection with entropy-driven guess scoring, delivered through a dark-themed GUI.

## What it does

- Loads a full Wordle word list with frequency-derived probabilities.
- Uses a precomputed response-pattern matrix to evaluate candidate words fast.
- Suggests high-entropy guesses for narrowing the answer pool and high-probability candidate words for final solves.
- Tracks user guesses and feedback through a graphical interface.

## Key files (code)

- `Engine.py` — core solver logic. Calculates word score based on expected entropy and candidate win probability.
- `GUI.py` — CustomTkinter application for entering guesses, selecting feedback colors, and viewing suggestions.
- `Data.py` — builds `scientific_word_data.csv` from `valid_guesses.csv` and `valid_solutions.csv` using word frequency weights (must run for first time only).
- `Matrix_init.py` — not required to run the GUI directly, but used to initialize word/probability data and related matrix `wordle_full_matrix.npy` for engine to work (must run for first time only, runs after Data.py).
- `scientific_word_data.csv` — preprocessed word list with probability weights.
- `wordle_full_matrix.npy` — precomputed Wordle response patterns for fast filtering.
- `requirements.txt` — project dependencies.

## How it works

1. `WordleEngine` loads word probabilities and the pattern matrix.
2. Each guess is scored by entropy across remaining possible answers.
3. The GUI displays:
   - `STRATEGIC SUGGESTIONS` for strong information-gathering guesses.
   - `ANSWER LIKELIHOOD` for likely solutions based on current game state.
4. After submitting guess feedback, the solver filters possible answers and refreshes recommendations.

## Requirements to run code

- Python 3.12.0
- `numpy`
- `pandas`
- `customtkinter`
- `wordfreq`

 all of which and more could be found in `requirements.txt`, make sure to initialize a venv.

## Running the app

From the repository root:

```bash
python GUI.py
```

or just run the executeble file in release.

Then enter your 5-letter guess, set the feedback colors, and submit to update the solver state.

## Download & Play

No Python installation required.

1. Go to the [Releases](https://github.com/Muhammad-H-Bakr/Wordle_Solver/releases) page.
2. Download `Wordle-Strat-Console.exe`.
3. Run and solve.

SHA-256: 18816F04DDB5C6892F349298AA9D98A2BEFF077E58B6206BEA9A0BB403F21312

## References

- 3B1B Wordle: [Repo](https://github.com/3b1b/videos/tree/e317d6c5eaa8370a2deb4d148c246b0d0e9fbe6f/_2022/wordle)
- Wordle words: [Dataset](https://www.kaggle.com/datasets/bcruise/wordle-valid-words/data)
