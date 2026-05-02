# Wordle Solver

A Python-based Wordle assistant that combines probability-weighted candidate selection with entropy-driven guess scoring, delivered through a dark-themed GUI.

## What it does

- Loads a full Wordle word list with frequency-derived probabilities.
- Uses a precomputed response-pattern matrix to evaluate candidate words fast.
- Suggests high-entropy guesses for narrowing the answer pool and high-probability candidate words for final solves.
- Tracks user guesses and feedback through a graphical interface.

## Key files

- `Engine.py` — core solver logic. Calculates word score based on expected entropy and candidate win probability.
- `GUI.py` — CustomTkinter application for entering guesses, selecting feedback colors, and viewing suggestions.
- `Data.py` — builds `scientific_word_data.csv` from `valid_guesses.csv` and `valid_solutions.csv` using word frequency weights (must run for first time only).
- `Matrix_init.py` — not required to run the GUI directly, but used to initialize word/probability data and related matrices for engine to work (must run for first time only, runs after Data.py).
- `scientific_word_data.csv` — preprocessed word list with probability weights.
- `wordle_full_matrix.npy` — precomputed Wordle response patterns for fast filtering.

## How it works

1. `WordleEngine` loads word probabilities and the pattern matrix.
2. Each guess is scored by entropy across remaining possible answers.
3. The GUI displays:
   - `STRATEGIC SUGGESTIONS` for strong information-gathering guesses.
   - `ANSWER LIKELIHOOD` for likely solutions based on current game state.
4. After submitting guess feedback, the solver filters possible answers and refreshes recommendations.

## Requirements

- Python
- `numpy`
- `pandas`
- `customtkinter`
- `wordfreq`

## Running the app

From the repository root:

```bash
python GUI.py
```

Then enter your 5-letter guess, set the feedback colors, and submit to update the solver state.
