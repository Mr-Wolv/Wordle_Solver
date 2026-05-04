# Wordle Solver – Entropy‑Powered Strategy Console

![Python](https://img.shields.io/badge/Python-3.12.0-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-GPL-v3)
![GUI](https://img.shields.io/badge/GUI-CustomTkinter-darkorange)
![Release](https://img.shields.io/badge/release-exe-9cf)

A **Python-based Wordle assistant** that combines probability‑weighted candidate selection with entropy‑driven guess scoring, delivered through a dark‑themed tactical GUI.  
Inspired by [3Blue1Brown’s Wordle video & code](https://github.com/3b1b/videos/tree/e317d6c5eaa8370a2deb4d148c246b0d0e9fbe6f/_2022/wordle).

---

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start (No Python Required)](#quick-start-no-python-required)
- [Installation & Running from Source](#installation--running-from-source)
- [How to Use the GUI](#how-to-use-the-gui)
- [Project Architecture](#project-architecture)
- [Algorithm Deep Dive](#algorithm-deep-dive)
- [File Inventory](#file-inventory)
- [Development Setup](#development-setup)
- [Dependencies](#dependencies)
- [License & Credits](#license--credits)
- [Addendum](#addendum)

---

## What It Does

- **Loads a full Wordle word list** with real‑world frequency‑derived probabilities (Zipf scale → linear weights).
- **Uses a precomputed response‑pattern matrix** (`wordle_full_matrix.npy`) to evaluate every possible guess against every possible secret **instantly**.
- **Scores every guess** by its *expected information gain* (Shannon entropy) and, when appropriate, its *win probability*.
- **Suggests two kinds of moves:**
  - **Strategic Suggestions** – high‑entropy words to **narrow** the remaining answer pool.
  - **Answer Likelihood** – high‑probability candidate words for **final solves**.
- **Tracks your game** in a 6‑row visual progression grid, showing colour‑coded feedback after each guess.
- **Adapts its scoring strategy** as the game progresses (pessimistic early, balanced mid, aggressive late).

---

## Quick Start (No Python Required)

1. Go to the [Releases page](https://github.com/Muhammad-H-Bakr/Wordle_Solver/releases).
2. Download `Wordle-Strat-Console.exe`.
3. Run the executable – the GUI opens immediately.

> ⚠️ Windows Defender or other antivirus may flag the unsigned `.exe`. The source is fully open – You can exclude it from the defender or build it yourself with pyinstaller from the job written in: `.github/workflows/build-exe.yml`.

---

## Installation & Running from Source

### 1. Clone the Repository

```bash
git clone https://github.com/Mr-Wolv/Wordle_Solver.git
cd Wordle_Solver
```

### 2. Set Up a Virtual Environment (recommended)

```bash
python -m venv venv
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

The project requires Python 3.12 (specifically 3.12.0 or higher).

### 4. Prepare the Data (first time only)

Quick steps:

```bash
python Data.py
python Matrix_init.py #runs only after Data.py
```

### 5. Launch the Solver

```bash
python GUI.py
```

## How to Use the GUI

The interface is divided into three panels:

| Panel | What it shows |
| ----------------- | ------------------------------------------------------------------------------ |
| **Left – Mission Progression** | Your last 6 guesses with colour feedback *(green/yellow/grey)*. |
| **Centre – Command Input** | 5-letter guess entry, colour selector buttons, **Submit/Reset** controls. |
| **Right – Intel Report** | Two scrollable lists: **Strategic Suggestions** (top) and **Answer Likelihood** (bottom). |

## Typical Play Session

1. Type a 5‑letter starter (e.g., CRANE) in the input field.

2. Set the feedback for each letter by clicking the colour boxes (G = green, Y = yellow, X = grey).

3. Click SUBMIT. The engine filters the answer pool and refreshes the suggestion lists.

4. Repeat until the pool is narrowed to a single word (or you see “Answer Likelihood” at 100%).

## Resetting

Click the RESET button any time to start a new game (clears state and reloads the full word list).

## Project Architecture

Wordle_Solver/

├── Engine.py                  # Core solver logic

├── GUI.py                     # CustomTkinter application

├── Data.py                    # Builds probability‑weighted word list

├── Matrix_init.py             # Precomputes full pattern matrix

├── scientific_word_data.csv   # Preprocessed word data (output of Data.py)

├── wordle_full_matrix.npy     # Precomputed pattern matrix (output of Matrix_init.py)

└── requirements.txt           # Dependencies

> The engine and the GUI are completely decoupled. `Engine.py` can be used headlessly in a script, a Jupyter notebook, or another front‑end.

## Algorithm Deep Dive

### 1. Word Probabilities

`Data.py` fetches the Zipf frequency of every word (a log‑scale measure of how common a word is in real English).
Zipf values are converted to linear weights so they can be treated as probabilities.

The resulting file `scientific_word_data.csv` contains each word and its probability.

### 2. Pattern Matrix

`Matrix_init.py` precomputes every possible (guess, secret) pattern and stores it as a single 2‑D uint8 array.
A pattern is a 5‑tuple of {0=grey, 1=yellow, 2=green} encoded as a base‑3 integer (0‑242).

> This matrix allows the engine to filter the candidate pool with a single vectorised operation.

Storage: ~168 MB for the default word list (≈13,000 × 13,000).

### 3. Entropy Scoring

For each guess, the engine:

A. Extracts the row of the pattern matrix corresponding to that guess, but only for the currently possible answers.

B. Computes the weighted Shannon entropy of the resulting pattern distribution:

>entropy = - Σ p(pattern) × log₂(p(pattern))
where p(pattern) is the sum of the normalised probabilities of all remaining answers that would give that pattern.

C. Combines entropy with the win probability of the guess (if it is a candidate answer) according to a phase‑aware scoring function:

| Turn                         | Strategy                                 | Score Formula                          |
|------------------------------|------------------------------------------|----------------------------------------|
| 1–2                          | Pessimistic (pure info-gathering)        | `score = entropy`                      |
| 3–4 and >2 candidates        | Balanced                                 | `score = entropy + 0.05 × win_prob`    |
| ≤2 candidates                | Aggressive                               | `score = entropy + 5.0 × win_prob`     |
| Later (else)                 | Greedy win                               | `score = entropy + 10.0 × win_prob`    |

>This heuristic follows the intuition that early guesses should maximise information (even if they can’t win), while later guesses should prioritise actually hitting the answer.

### 4. State Update

When the user submits a guess and its feedback pattern, the engine simply keeps only those indices from possible_indices where the pre‑stored pattern matches the observed one.

## File Inventory

| File | Purpose | Must Run? |
| :--- | :--- | :--- |
| `Data.py` | Downloads word frequencies and builds `scientific_word_data.csv` | Once (first-time setup) |
| `Matrix_init.py` | Builds the full pattern matrix `wordle_full_matrix.npy` | Once (after `Data.py`) |
| `Engine.py` | Core solver class (`wordleEngine`) | No (imported by GUI) |
| `GUI.py` | The CustomTkinter desktop application | Entry point |
| `requirements.txt` | All Python packages needed | Install once |
| `scientific_word_data.csv` | Pre-computed word probabilities | Generated (By Data.py) |
| `wordle_full_matrix.npy` | Pre-computed pattern matrix | Generated (By Matrix_init.py) |

## First‑Time Setup (Data Preparation)

The solver needs two files that are stored in this repository but are also avaliable in kaggle:

- `valid_guesses.csv` – list of all allowed guess words.

- `valid_solutions.csv` – list of words that can be the hidden answer.

Reference to them: [Kaggle](https://www.kaggle.com/datasets/bcruise/wordle-valid-words/data)

> After `Data.py` runs it produces `scientific_word_data.csv` (contains ~13,000 words with normalised probabilities) which is then fed to `Matrix_init.py` that creates `wordle_full_matrix.npy` (~168 MB). The computation takes a few minutes on a modern CPU. (5-7 minute approx).

Verify that both generated files exist in the root directory if you were running `GUI.py`.

Note: The pre‑built executable already bundles a pre‑computed matrix and everyother thing, no extra required (not even python).

## Development Setup

```bash
git clone https://github.com/Mr-Wolv/Wordle_Solver.git
cd Wordle_Solver
python -m venv venv   
venv\Scripts\activate
pip install -r requirements.txt
# follow first-time setup above:
# python Data.py
# python Matrix_init.py
python GUI.py
```

## Dependencies

All required packages are listed in `requirements.txt`.

Key libraries:

| Library | Why |
| :--- | :--- |
| `numpy` | Matrix operations, fast entropy calculation |
| `pandas` | CSV data loading and processing |
| `customtkinter` | Modern dark-themed GUI |
| `wordfreq` | Real-world word frequency (Zipf scale) |
| `pyinstaller` | (optional) Build standalone `.exe` |

## License & Credits

- 3Blue1Brown’s Wordle analysis.
- Word lists sourced from the Kaggle Wordle dataset.
- Code by Me, under The GNU General Public License v3.0 (GPLv3).

## Addendum

**A Note on Hard Mode**:

In normal Wordle mode, the *solver* is not, strictly speaking, a flawless solver — it's a well-defined heuristic. It never needed more than 6 guesses in all my tests (I found no case that shows failure in normal mode, but I leave a margin just to avoid any unaddressed edge cases), and it averages a crisp ~3.7 turns. It was, I dare say, a beautiful, successful experiment.

Hard mode, however, tells a different story. Here the solver becomes a genuine *approximator* — there is no doubt. The average is still respectable at ~3.8, but in roughly 1% of games it stumbles to 7+ turns. These stubborn cases arise when the remaining word pool contains linguistic neighbors — words sharing 3 or 4 letters — that the algorithm struggles to tease apart. The culprit is often the first guess, but also the rules of hard mode, which disallow "burner words." In normal mode, you can sacrifice the immediate win by playing a burner word that eliminates many candidates at once, efficiently pruning the space and guaranteeing victory in the next move or two. Hard mode forbids this; you are forced to reuse the letters you’ve already locked in, and so you can get trapped in a slow-motion guessing loop.

I built this project for normal mode, and the mathematics rose to the occasion. Hard mode, though, exposes a subtle frontier: when strategy exhausts its tools, the game reverts, briefly, to a guessing game. It's a humbling reminder that even elegant logic has its edges.
