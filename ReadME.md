# Wordle Solver – Entropy‑Powered Strategy Console

![Python](https://img.shields.io/badge/Python-3.12.0-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-GPL-v3)
![GUI](https://img.shields.io/badge/GUI-CustomTkinter-darkorange)
![Release](https://img.shields.io/badge/release-exe-9cf)

A **Python-based Wordle assistant** that combines probability‑weighted candidate selection with entropy‑driven guess scoring and worst‑case (minimax) awareness, delivered through a dark‑themed tactical GUI.  
Inspired by [3Blue1Brown's Wordle video & code](https://github.com/3b1b/videos/tree/e317d6c5eaa8370a2deb4d148c246b0d0e9fbe6f/_2022/wordle).

---

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start (No Python Required)](#quick-start-no-python-required)
- [Installation & Running from Source](#installation--running-from-source)
- [How to Use the GUI](#how-to-use-the-gui)
- [Project Architecture](#project-architecture)
- [Algorithm Deep Dive](#algorithm-deep-dive)
- [Performance Benchmarks](#performance-benchmarks)
- [Profiling the Engine](#profiling-the-engine)
- [File Inventory](#file-inventory)
- [Development Setup](#development-setup)
- [Dependencies](#dependencies)
- [License & Credits](#license--credits)

---

## What It Does

- **Loads a full Wordle word list** with real‑world frequency‑derived probabilities (Zipf scale → linear weights).
- **Uses a precomputed response‑pattern matrix** (`wordle_full_matrix.npy`) to evaluate every possible guess against every possible secret **instantly**.
- **Scores every guess** by its *expected information gain* (Shannon entropy), *worst-case bucket size* (minimax penalty to avoid clusters), and *win probability*.
- **Suggests two kinds of moves:**
  - **Strategic Suggestions** – high‑entropy words to **narrow** the remaining answer pool.
  - **Answer Likelihood** – high‑probability candidate words for **final solves**.
- **Tracks your game** in a 6‑row visual progression grid, showing colour‑coded feedback after each guess.
- **Adapts its scoring strategy** as the game progresses (early info‑gathering, balanced mid, aggressive late).
- **Handles Hard Mode** by searching the full dictionary for cluster‑breaking words (matching real Wordle hard mode rules).

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
python Matrix_init.py        # runs only after Data.py
```

### 5. Launch the Solver

```bash
python GUI.py
```

---

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
4. Repeat until the pool is narrowed to a single word (or you see "Answer Likelihood" at 100%).

## Resetting

Click the RESET button any time to start a new game (clears state and reloads the full word list).

---

## Project Architecture

```
Wordle_Solver/
├── Engine.py                  # Core solver logic
├── GUI.py                     # CustomTkinter application
├── utils.py                   # Shared utilities (resource_path)
├── Data.py                    # Builds probability‑weighted word list
├── Matrix_init.py             # Precomputes full pattern matrix
├── benchmark.py               # Performance benchmark (multi‑process)
├── profiler.py                # cProfile hot‑spot analyser
├── tester.py                  # CI‑compatible test harness
├── scientific_word_data.csv   # Preprocessed word data (output of Data.py)
├── wordle_full_matrix.npy     # Precomputed pattern matrix (output of Matrix_init.py)
└── requirements.txt           # Dependencies
```

> The engine, GUI, and benchmarking are completely decoupled. `Engine.py` can be used headlessly in a script, Jupyter notebook, or another front‑end.

---

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

### 3. Entropy + Minimax Scoring

For each guess, the engine:

A. Extracts the row of the pattern matrix corresponding to that guess, but only for the currently possible answers.

B. Computes the weighted Shannon entropy of the resulting pattern distribution:

> entropy = - Σ p(pattern) × log₂(p(pattern))

C. Computes the **worst-case** remaining pool fraction (the largest pattern bucket). This acts as a minimax penalty — guesses with a large worst-case bucket are penalised because they risk getting stuck in word clusters (e.g., `?ATCH`, `?OUND`).

D. Combines entropy, worst-case penalty, and win probability according to a phase‑aware scoring function:

| Phase | Condition | Score Formula |
|---------|-----------|----------------|
| **Endgame** | ≤2 candidates | `entropy + 10.0 × win_prob` |
| **Early** | Turns 1–2 | `entropy – early_penalty × worst_case` |
| **Danger** | ≤5 std / ≤10 hard pool, or turn ≥4 and worst_case > 0.35 | `entropy – max_penalty × worst_case + 0.5 × win_prob` |
| **Mid‑Late** | Everything else | `entropy – turn_penalty × worst_case + 5.0 × win_prob` |

Where penalties grow with turn number:

| Mode | Early Penalty | Max Penalty | Penalty Ramp |
|------|--------------|-------------|--------------|
| Standard | 0.3 | 3.0 | 0.5 + 0.4 × turn |
| Hard | 1.2 | 4.0 | 1.0 + 0.5 × turn |

> The **worst-case penalty** is the key algorithmic improvement over a pure-entropy approach. It prevents the solver from picking guesses that leave a large, ambiguous bucket of similar words — the exact failure mode that plagues naive entropy solvers in both normal and hard mode.

### 4. Hard Mode — Full‑Dictionary Search

In real Wordle **hard mode**, you are allowed to use **any valid Wordle word** as a guess — you just must respect previously revealed clues (greens stay in position, yellows must appear somewhere). The engine reflects this: when the candidate pool is small (≤ 10), it searches the **full 13,000‑word dictionary** for cluster‑breaking guesses, not just the remaining answer candidates. This gives access to words that can distinguish between symmetrically similar answers (e.g., distinguishing `CATCH` from `HATCH` by using a word that tests the first letter differently).

When the pool is larger, the engine restricts to candidates for performance (the extra words don't help when the answer space is still broad).

### 5. State Update

When the user submits a guess and its feedback pattern, the engine simply keeps only those indices from `possible_indices` where the pre‑stored pattern matches the observed one.

### 6. Performance Optimisations

- **O(1) word lookup** via a `word_to_idx` dictionary (was O(n) `.index()` scan).
- **O(1) membership** via a boolean `possible_mask` array (was O(n) `np.where` + `in` check inside the 13K‑iteration hot loop).
- **Precomputed `full_weights`** — zero‑cost `win_prob` lookup inside the scoring loop.
- **Memory‑mapped matrix** (`mmap_mode='r'`) — test workers share OS pages instead of each loading 168 MB into RAM.
- **In hard mode**, candidate‑only search is used when the pool is large (fast path), with full‑dictionary search only when the pool is small enough to need it.

---

## Performance Benchmarks

Run with: `python benchmark.py --samples 200`

| Mode | Samples | Accuracy | Avg Turns | Failures | Throughput |
|------|---------|----------|-----------|----------|------------|
| Normal | 200 | **100.00%** | 3.76 | **0** | 0.35 words/sec |
| Hard | 300 | **100.00%** | 3.68 | **0** | 0.44 words/sec |

Turn distribution (30‑sample benchmark):

| Turns | Normal Mode | Hard Mode |
|-------|-----------|-----------|
| 2 | — | 1 (3.3%) |
| 3 | 17 (56.7%) | 11 (36.7%) |
| 4 | 9 (30.0%) | 8 (26.7%) |
| 5 | 4 (13.3%) | 6 (20.0%) |
| 6 | — | 4 (13.3%) |

> **100% solve rate in both modes** across all tested samples. The worst‑case penalty eliminates the earlier ~1% failure rate in hard mode.

---

## Profiling the Engine

Run with: `python profiler.py --word CRANE`

The profiler uses cProfile to identify the hottest functions. The primary bottleneck is the **entropy scoring loop** in `get_suggestions()`:

- ~90% of CPU time is spent inside the `for i in search_indices:` loop
- Each iteration performs: matrix indexing, `np.bincount`, log₂ calculation, and phase‑aware scoring
- With ~13,000 search words and ~4 guesses per game, that's **~52,000 entropy evaluations per game**

The loop is inherently O(n × m) where n = search space size and m = candidate pool size. For normal mode this is O(13K × 13K) in the worst case, but each evaluation uses vectorised numpy operations over the candidate pool.

**To profile deeper:** save the profile with `--save results.prof` and open with `snakeviz results.prof`.

---

## File Inventory

| File | Purpose | Must Run? |
| :--- | :--- | :--- |
| `Data.py` | Downloads word frequencies, builds `scientific_word_data.csv` | Once (first‑time setup) |
| `Matrix_init.py` | Builds the full pattern matrix `wordle_full_matrix.npy` | Once (after `Data.py`) |
| `Engine.py` | Core solver class (`WordleEngine`) | No (imported by GUI) |
| `GUI.py` | CustomTkinter desktop application | Entry point |
| `utils.py` | Shared utilities (e.g., `resource_path` for PyInstaller) | No (imported) |
| `tester.py` | CI‑compatible multi‑process test harness | Optional |
| `benchmark.py` | Detailed performance benchmark with turn distribution | Optional |
| `profiler.py` | cProfile hot‑spot analyser | Optional |
| `requirements.txt` | All Python packages needed | Install once |
| `scientific_word_data.csv` | Word probabilities (generated by `Data.py`) | Generated |
| `wordle_full_matrix.npy` | Pattern matrix (generated by `Matrix_init.py`) | Generated |
| `valid_solutions.csv` | Kaggle‑sourced answer word list | Original data |
| `valid_guesses.csv` | Kaggle‑sourced guess word list | Original data |

---

## First‑Time Setup (Data Preparation)

The solver needs two files from Kaggle:

- `valid_guesses.csv` – list of all allowed guess words.
- `valid_solutions.csv` – list of words that can be the hidden answer.

Reference: [Kaggle Wordle Dataset](https://www.kaggle.com/datasets/bcruise/wordle-valid-words/data)

> After `Data.py` runs it produces `scientific_word_data.csv` (~13,000 words with normalised probabilities) which is then fed to `Matrix_init.py` that creates `wordle_full_matrix.npy` (~168 MB). The computation takes a few minutes on a modern CPU (5–7 minutes approx).

Note: The pre‑built executable already bundles the pre‑computed matrix — no extra setup required (not even Python).

---

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

---

## Dependencies

All required packages are listed in `requirements.txt`.

Key libraries:

| Library | Why |
| :--- | :--- |
| `numpy` | Matrix operations, fast entropy calculation |
| `pandas` | CSV data loading and processing |
| `customtkinter` | Modern dark‑themed GUI |
| `wordfreq` | Real‑world word frequency (Zipf scale) |
| `pyinstaller` | (optional) Build standalone `.exe` |

---

## License & Credits

- 3Blue1Brown's Wordle analysis and original information‑theory approach.
- Word lists sourced from the [Kaggle Wordle dataset](https://www.kaggle.com/datasets/bcruise/wordle-valid-words/data).
- Code by Me, under the GNU General Public License v3.0 (GPLv3).
