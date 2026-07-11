# Wordle Solver – Entropy‑Powered Strategy Console

![Python](https://img.shields.io/badge/Python-3.12.0-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-GPL-v3)
![GUI](https://img.shields.io/badge/GUI-WebView2-9cf)
![Release](https://img.shields.io/badge/release-exe-9cf)

A **Python-based Wordle assistant** that combines probability‑weighted candidate selection with entropy‑driven guess scoring and worst‑case (minimax) awareness, delivered through a dark‑themed WebView2 desktop app and a browser web UI. 
Inspired by [3Blue1Brown's Wordle video & code](https://github.com/3b1b/videos/tree/e317d6c5eaa8370a2deb4d148c246b0d0e9fbe6f/_2022/wordle).

---

## Table of Contents

- [What It Does](#what-it-does)
- [Quick Start (No Python Required)](#quick-start-no-python-required)
- [Installation & Running from Source](#installation--running-from-source)
- [How to Use the Web UI](#how-to-use-the-web-ui)
- [Project Architecture](#project-architecture)
- [Algorithm Deep Dive](#algorithm-deep-dive)
- [Performance Benchmarks](#performance-benchmarks)
- [Profiling the Engine](#profiling-the-engine)
- [Testing](#testing)
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
2. Download the `Wordle-Strat-Console` folder (the one-folder bundle).
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
python build_matrix.py      # bakes the answer-only pattern matrix (seconds)
```

### 5. Launch the Solver

**Desktop app (recommended):** builds a native window around the web UI.

```bash
python -m wordle_solver.desktop.desktop_app     # native WebView2 window (backend + DOM UI bundled)
```

**Web server (dev / headless):** run the FastAPI backend + DOM frontend in a browser.

```bash
python -m wordle_solver.app.web_server      # serves http://127.0.0.1:8000
```

Both wrap the same `wordle_solver.engine` backend.

---

## How to Use the Web UI

The interface is a three-card layout:

| Card | What it shows |
| ----------------- | ------------------------------------------------------------------------------ |
| **Left – Game Board** | Your last 6 guesses as coloured tiles (green/yellow/grey), the colour legend, and the HARD MODE toggle. |
| **Centre – Your Move** | 5-letter guess entry, clickable colour tiles (click a tile to cycle absent → present → correct), SUBMIT, the NYT HINT logger, and SYSTEM RESET. |
| **Right – Strategy** | Two lists: **SOLVE** (best words to play next, ranked by score) and **SHRED** (worst-case splitters, ranked by win-probability). |

## Typical Play Session

1. Type a 5‑letter starter (e.g., CRANE) in the guess field — entry tiles appear below it.
2. Click each tile to set the colour from your real Wordle feedback (grey = absent, yellow = present, green = correct).
3. Click SUBMIT. The engine filters the answer pool and refreshes the board + suggestion lists.
4. Repeat until the board shows the solved banner (pool collapsed to one word).

## Resetting

Click the RESET button any time to start a new game (clears state and reloads the full word list).

---

## Project Architecture

```
Wordle_Solver/
├── src/wordle_solver/            # the installable package (single import root)
│   ├── __init__.py               # public surface: WordleEngine, score_guesses, play_one_game
│   ├── utils.py                  # resource_path (PyInstaller-safe asset resolution)
│   ├── engine/
│   │   ├── lexicon.py            # Word/answer data + the 2315×2315 pattern matrix (PatternMatrix)
│   │   ├── scoring.py            # Vectorized information-gain scoring (np.add.at)
│   │   ├── patterns.py           # Canonical pattern math + the SINGLE shared exact minimax
│   │   ├── engine.py             # Solver controller: state, hard-mode rule, hints, caches, specialists
│   │   └── game.py               # Headless self-play (play_one_game; used by benchmarks/tests)
│   ├── app/
│   │   ├── web_server.py         # FastAPI backend wrapping the engine + JSON state API (serves web/)
│   │   └── cli.py                # Terminal solver
│   ├── desktop/
│   │   ├── desktop_app.py        # Native desktop wrapper: web_server in a thread + pywebview (WebView2)
│   │   ├── build_dist.py         # Reproducible one-folder PyInstaller build
│   │   └── desktop_app.spec      # PyInstaller spec for the one-folder bundle
│   └── generators/               # OFFLINE artifact builders (not imported at runtime)
│       ├── build_word_data.py    # Probability-weighted word list (scientific_word_data.csv)
│       ├── build_matrix.py       # Vectorized builder for the answer-only pattern matrix
│       ├── build_residual_optimal.py  # residual_optimal.json (optimal-minimax sub-trees)
│       ├── build_nohint_tree.py  # residual_optimal_nohint.json (hard no-hint closure tree)
│       ├── find_t1_h.py          # Family-safe turn-1 'h' opening (t1_h_opening.json)
│       ├── prove_hard_ceiling.py # Prover for the hard no-hint structural ceiling
│       └── build_all.py          # Orchestrates every generator in order (python -m …)
├── web/                          # Real DOM frontend (index.html, styles.css, app.js) — primary UI
├── benchmark.py / profiler.py / tester.py  # Optional dev tools
├── test_*.py                     # pytest suite (engine, scoring, lexicon, cli, web, app, game contract)
├── valid_solutions.csv           # The 2,315 official NYT answers (source data)
├── valid_guesses.csv             # The ~12,972 allowed guess words (source data)
├── wordle_full_matrix.npy        # Precomputed pattern matrix (output of build_matrix.py)
├── turn1_cache.json              # Precomputed turn-1 suggestions (output of the engine, cached)
├── residual_optimal.json         # Residual-cluster optimal trees (output of build_residual_optimal.py)
├── residual_optimal_nohint.json # Hard no-hint closure tree (output of build_nohint_tree.py)
├── t1_h_opening.json             # Family-safe turn-1 'h' opening index (output of find_t1_h.py)
└── requirements.txt              # Dependencies
```

> The engine, web/desktop front-ends, and benchmarking are completely
> decoupled. `wordle_solver.engine` is a thin controller over `lexicon.py`
> (data + matrix) and `scoring.py` (math) and can be used headlessly in a
> script, Jupyter notebook, or another front-end. All exact minimax lives in
> `wordle_solver.engine.patterns` so the live solver and the offline builders
> never drift.



## Algorithm Deep Dive

### 1. Word Probabilities

`build_word_data.py` fetches the Zipf frequency of every word (a log‑scale measure of how common a word is in real English).
Zipf values are converted to linear weights so they can be treated as probabilities.

The resulting file `scientific_word_data.csv` contains each word and its probability.

### 2. Pattern Matrix

`build_matrix.py` precomputes the pattern for every (guess, secret) pair
where **both** are valid NYT answers, and stores it as a single 2‑D int16
array. A pattern is a 5‑tuple of {0=grey, 1=yellow, 2=green} encoded as a
base‑3 integer (0‑242). The build is fully vectorized (one numpy call per
guess over all answers) and finishes in seconds.

> The solver's candidate universe is the 2,315 official answers, not the
> ~12,972‑word dictionary, so the matrix is **2315 × 2315 ≈ 10.7 MB** (1/16th
> the old full matrix). A SHRED opener that isn't itself an answer has its
> pattern row computed on the fly, vectorized, so it costs nothing to store.

Storage: ~10.7 MB (2,315 × 2,315), down from ~168 MB.

### 3. Entropy + Minimax Scoring (Optimised for Average Turns)

For each guess, the engine:

A. Extracts the row of the pattern matrix corresponding to that guess, but only for the currently possible answers.

B. Computes the weighted Shannon entropy of the resulting pattern distribution:

> entropy = - Σ p(pattern) × log₂(p(pattern))

C. Computes the **worst-case** remaining pool fraction (the largest pattern bucket). A light minimax penalty prevents truly catastrophic splits while preserving information gain.

D. Combines entropy, worst-case penalty, and win probability according to a phase‑aware scoring function (constants live at the top of `Engine.py`):

| Phase | Condition | Score Formula |
|---------|-----------|----------------|
| **Endgame** | ≤2 candidates | `entropy + ENDGAME_WIN_BONUS × win_prob` |
| **Minimax** | ≤5 candidates | `–100.0 × worst_case + 0.01 × entropy + win_prob` |
| **Early** | Turns 1–2 | `entropy – STD/HARD_EARLY_WC_PENALTY × worst_case` |
| **Mid–Late** | Everything else | `entropy – turn_penalty × worst_case + WIN_BONUS_WEIGHT × win_prob` |

Penalties grow with turn number and differ by mode:

| Mode | Early Penalty | Turn Penalty (turn ≥ 3) | Max Penalty |
|------|--------------|--------------|-------------|
| Standard | `STD_EARLY_WC_PENALTY = 3.1` | `STD_TURN_PENALTY = 3.0` (ramps down to 0) | — |
| Hard | `HARD_EARLY_WC_PENALTY = 4.5` | `HARD_BASE_PENALTY + turn × HARD_PENALTY_PER_TURN`, capped at `HARD_MAX_PENALTY = 10.0` | 10.0 |

> The scoring is tuned for **average turns** rather than worst-case guarantees. A meaningful early-turn worst-case penalty keeps splits sane while entropy still dominates information gain; gentle late-game penalties prevent pathological clusters without sacrificing average performance.

### 4. Candidate-Space Search (Both Modes)

The candidate universe is the **2,315 valid NYT answers**, not the full ~12,972-word dictionary. A legal guess is an answer *or* a word already consistent with the revealed clues (proven sufficient — non-answer openers only matter on turn 1 to break clusters), so the search space starts at 2,315 and shrinks as the pool collapses. This is essential for breaking symmetric word clusters (e.g., `?ATCH`, `?UNCH`): an opener can distinguish between `CATCH`, `HATCH`, `MATCH` etc. far better than any late candidate could.

In hard mode the engine **enforces the NYT hard-mode rule**: every guess must stay consistent with all clues revealed so far. The set of legal guesses is exactly the current candidate pool (`possible_indices`) — any word outside it would contradict an already-observed green/yellow/grey — so hard mode simply restricts the search to that pool. This is correct-by-construction and a speed-up (the hot loop shrinks to the pool). Hard mode is *genuinely harder* than normal: without hints it solves **100%** (2315/2315) in ~3.58 avg turns via the HARD no-hint optimal-shredder tree (`residual_optimal_nohint.json`); with the NYT hint button (a real in-game mechanic) it reaches 100% at ~3.10 avg turns. The former 6 hard no-hint failures (`foyer`/`hound`/`mound`/`hatch`/`hunch`/`latch`) are all closed by the shredder tree — zero structural ceiling remains.

### 5. State Update

When the user submits a guess and its feedback pattern, the engine simply keeps only those indices from `possible_indices` where the pre‑stored pattern matches the observed one.

### 6. Performance Optimisations

- **O(1) word lookup** via a `word_to_idx` dictionary (was O(n) `.index()` scan).
- **O(1) membership** via a boolean `possible_mask` array (was O(n) `np.where` + `in` check inside the 13K‑iteration hot loop).
- **Precomputed `full_weights`** — zero‑cost `win_prob` lookup inside the scoring loop.
- **Memory‑mapped matrix** (`mmap_mode='r'`) — the 10.7 MB answer matrix is shared from OS pages instead of copied into each process.
- **Turn-1 cache** — the first-turn scoring (13K evaluations) is computed once and cached for the lifetime of the process, saving ~4 seconds on every subsequent game.
- **Full-dictionary search** on every turn — no early termination, guaranteeing the best possible suggestion at all times.

---

## Performance Benchmarks

Run with: `python benchmark.py --samples 200` (add `--hints` to simulate the NYT hint button, `--mode hard` for hard mode, `--json` for machine output).

The NYT **hint button is a real, first-class game mechanic** — exactly one consonant AND one vowel, revealed by the game itself. It is *not* cheating; it is part of how Wordle is played. Supplying the hint is therefore the intended path to the 100% solve target, and the engine models it faithfully (see the Hint gating / Hint tests). Two distinct, honestly-labelled metrics exist:

- **No-hint perfect play (the *ceiling*)** — the solver plays optimally from turn 1 with no human error and no hint. This is the engine's own ceiling, not a prediction of human play.
- **Hint-assisted play** — the solver is also given the secret's unique letters one consonant + one vowel at a time (the in-game hint button). This is realistic play *with* the feature enabled.

> Numbers below are reproduced by a closed-loop self-play over **all 2,315** official NYT answers (not a sample). Run `python -m pytest -m exhaustive` to re-verify the no-hint contract; the hint-aware rows are reproduced by `python benchmark.py --samples 2315 --hints --mode both`.

### Exhaustive solve-rate (all 2,315 NYT answers)

| Mode | No hints (ceiling) | With NYT hint button (1 consonant + 1 vowel) |
|------|----------|-------------------------------------------|
| **Normal** | **2315 / 2315 (100.0%)** · avg 3.63 | **2315 / 2315 (100.0%)** · avg 3.08 |
| **Hard** | **2315 / 2315 (100.0%)** · avg 3.58 | **2315 / 2315 (100.0%)** · avg 3.10 |

- **With hints: a perfect 2315/2315 in BOTH modes.** Hints resolve the last residual clusters the greedy solver otherwise can't close within 6 turns. This is the design target and the protected baseline — it must stay 100% across all future edits (see `test_game_contract.py::test_hinted_mode_is_perfect`).
- **Normal no-hint: 100%.** The earlier normal residuals (`bitty`, `foyer`, `valor`) are now closed by an optimal-minimax rescue that engages on small pools containing a known residual word.
- **Hard no-hint: 2315/2315 (100%).** The six former hard no-hint residuals (`foyer`, `hound`, `mound`, `hatch`, `hunch`, `latch`) are closed by the HARD no-hint optimal-shredder decision tree (`residual_optimal_nohint.json`, built by `wordle_solver.generators.build_nohint_tree`). Under the pool-only rule these formed a *documented* structural ceiling, but with non-answer shredders (legal NYT-hard guesses that split same-suffix sibling clusters) they are all solved in ≤6. The authoritative exact failure set is enforced by `test_game_contract.py::test_exhaustive_contract` with `EXPECTED_HARD_RESIDUALS = set()` (empty); any silent change in solver behavior that changes this set or drops the solve count is caught.

| Mode (sample benchmark, seed=42, n=300) | Accuracy | Avg Turns | Failures | Throughput |
|------|---------|----------|-----------|----------|
| Normal | **100%** (no hint) / **100%** with hints | **3.63** | 0 (no hint) | 4.8 games/sec |
| Hard | **100%** (no hint) / **100%** with hints | **3.58** | 0 (no hint) | 5.9 games/sec |

> The figures above reconcile with the exhaustive table: the 300-word
> sample (seed=42) by chance avoids most residual words. Trust the
> **all-2,315-word** rows above for the authoritative numbers.

Turn distribution (benchmark, seed=42):

| Turns | Normal Mode | Hard Mode |
|-------|-----------|-----------|
| 2 | ~1% | ~3% |
| 3 | ~47% | ~39% |
| 4 | ~38% | ~40% |
| 5 | ~13% | ~15% |
| 6 | ~1% | ~2% |
| 7+ | <1% | <1% |

> Without hints, Normal mode solves **100%** of all answers in **3.63** average turns and Hard **100%** in **3.58** — both within the 3–4 turn target and both at 100% no-hint. **With the NYT hint button (a real game mechanic), both modes stay at 100%** at ~3.08–3.10 avg turns. Per-turn suggestions are **~28 ms** (well under interactive thresholds); the first turn is cached after the opening game.

**Architecture wins (this build):**
- **Split** the monolith into `src/wordle_solver/engine/lexicon.py` (data + matrix), `scoring.py` (vectorized math), `engine.py` (controller), `patterns.py` (the single shared exact minimax), and `game.py` (headless self-play) — single responsibility, testable, and the desktop/web front-ends live under `src/wordle_solver/app/` and `src/wordle_solver/desktop/`.
- **Answer-only matrix** 2315×2315 ≈ 10.7 MB (was 168 MB) — 16× less disk/RAM, and `build_matrix.py` bakes it in seconds (was minutes, O(n²) Python loop).
- **Vectorized scoring** via `np.add.at` scatter — no Python per-guess loop.
- **Hint gating**: external hints restrict the answer universe via `hint_mask`, so SHRED/answers never violate a hint. The NYT hint button is modeled faithfully — **exactly one consonant AND one vowel** (2 total); a second of either category is rejected and the input locks once the budget is spent.
- **Residual optimal specialist**: a precomputed optimal-minimax sub-tree (`residual_optimal.json`, built by `build_residual_optimal.py`) is consulted only when the live pool enters one of the few residual clusters greedy can't close — keeping the greedy solver the default hot path (fast, simple) while guaranteeing 100% with hints.
- **Turn-1 `h` family-safe override** (`t1_h_opening.json`, built by `find_t1_h.py`): the single residual `hatch` — whose greedy opening would poison its cluster — is closed by playing the proven family-safe guess `abhor` at turn 1 **only when the hint is `h`**, so it can never affect a non-`h` word.


---

## Profiling the Engine

Run with: `python profiler.py --word CRANE`

The profiler uses cProfile to identify the hottest functions. After the optimizations above, the dominant cost per `get_suggestions()` call is:
- a single contiguous mmap row read per candidate guess (`engine.py:_score_words`),
- then a fully vectorized entropy/worst-case/win-prob pass in numpy.

A full 6-turn game is typically **<0.15 s**; per-turn suggestions are **~35 ms** (normal) and faster still in hard mode as the pool collapses. The turn-1 cache avoids recomputing the opener across games.

---

## Testing

The repo ships a pytest suite covering the engine, the scoring math, the
pattern matrix, the web/desktop contracts, and the game-contract gate:

```bash
pip install -r requirements.txt      # includes pytest
python -m pytest -q                  # fast suite (excludes the exhaustive gate)
python -m pytest -m exhaustive -q    # authoritative gate: replays all 2,315 answers, both modes
python -m pytest test_lexicon.py -v  # a single file, verbose
```

| Test file | What it proves |
|-----------|----------------|
| `test_engine.py` | State machine, pattern math, hard-mode legality (D1 regression), endgame shortcut, hint pruning, full games |
| `test_scoring.py` | `score_guesses` invariants: entropy beats worst-case, endgame formula, hard-mode penalty, pattern decode |
| `test_lexicon.py` | `PatternMatrix` vs brute-force `calculate_pattern` (answers + SHRED on-the-fly), symmetry, `row_for`/`rows` |
| `test_cli.py` | `cli.parse_pattern` accepts valid `02220` strings and rejects malformed input |
| `test_web.py` / `test_app_contract.py` | Web backend API + desktop boot/close contract |
| `test_game_contract.py` | Game contract + the exhaustive 100% no-hint gate (`-m exhaustive`) |

---

## File Inventory

| File | Purpose | Must Run? |
| :--- | :--- | :--- |
| `build_word_data.py` | Downloads word frequencies, builds `scientific_word_data.csv` | Once (first‑time setup) |
| `build_matrix.py` | Builds the answer-only pattern matrix `wordle_full_matrix.npy` | Once (after `build_word_data.py`) |
| `build_residual_optimal.py` | Builds `residual_optimal.json` (optimal-minimax sub-trees for the residual clusters) | Once |
| `build_nohint_tree.py` | Builds `residual_optimal_nohint.json` (hard no-hint closure tree) | Once |
| `find_t1_h.py` | Proves & writes `t1_h_opening.json` (family-safe turn-1 `h` opening = `abhor`) | Once |
| `src/wordle_solver/engine/lexicon.py` | Word/answer data + `PatternMatrix` (loads the matrix) | No (imported by the engine) |
| `src/wordle_solver/engine/scoring.py` | Vectorized information-gain scoring | No (imported by the engine) |
| `src/wordle_solver/engine/engine.py` | Solver controller class (`WordleEngine`) + specialists | No (imported by the front-ends) |
| `src/wordle_solver/app/cli.py` | Terminal solver | Optional |
| `src/wordle_solver/app/web_server.py` | FastAPI backend for the web/desktop UI | No (imported by desktop_app) |
| `src/wordle_solver/desktop/desktop_app.py` | pywebview desktop application | Entry point |
| `src/wordle_solver/desktop/desktop_app.spec` | PyInstaller build spec for the one-folder bundle | Build only |
| `src/wordle_solver/utils.py` | Shared utilities (e.g., `resource_path` for PyInstaller) | No (imported) |
| `src/wordle_solver/engine/game.py` | Headless self-play (benchmarks/tests) | No (imported) |
| `tester.py` | CI‑compatible multi‑process test harness | Optional |
| `benchmark.py` | Detailed performance benchmark with turn distribution | Optional |
| `profiler.py` | cProfile hot‑spot analyser | Optional |
| `test_engine.py` … `test_game_contract.py` | pytest suite (engine, scoring, lexicon, cli, web, app, contract) | Optional |
| `requirements.txt` | All Python packages needed | Install once |
| `scientific_word_data.csv` | Word probabilities (generated by `build_word_data.py`) | Generated |
| `wordle_full_matrix.npy` | Pattern matrix (generated by `build_matrix.py`) | Generated |
| `valid_solutions.csv` | Kaggle‑sourced answer word list (the 2,315 NYT answers) | Source data |
| `valid_guesses.csv` | Kaggle‑sourced guess word list (~12,972 allowed words) | Source data |
| `turn1_cache.json` | Precomputed turn-1 suggestions (cached by the engine) | Generated |
| `residual_optimal.json` | Precomputed residual-cluster optimal trees (generated by `build_residual_optimal.py`) | Generated |
| `residual_optimal_nohint.json` | Hard no-hint closure tree (generated by `build_nohint_tree.py`) | Generated |
| `t1_h_opening.json` | Family-safe turn-1 `h` opening index (generated by `find_t1_h.py`) | Generated |



## First‑Time Setup (Data Preparation)

The solver needs two files from Kaggle:

- `valid_guesses.csv` – list of all allowed guess words.
- `valid_solutions.csv` – list of words that can be the hidden answer.

Reference: [Kaggle Wordle Dataset](https://www.kaggle.com/datasets/bcruise/wordle-valid-words/data)

> After `build_word_data.py` runs it produces `scientific_word_data.csv` (~13,000 words with normalised probabilities) which is then fed to `build_matrix.py` that creates `wordle_full_matrix.npy` (~10.7 MB, the 2,315×2,315 answer matrix). The build is fully vectorized and finishes in seconds.

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
# python -m wordle_solver.generators.build_word_data
# python -m wordle_solver.generators.build_matrix
python -m wordle_solver.desktop.desktop_app   # launch the desktop (WebView2) app
```

---

## Dependencies

All required packages are listed in `requirements.txt`.

Key libraries:

| Library | Why |
| :--- | :--- |
| `numpy` | Matrix operations, fast entropy calculation |
| `pandas` | CSV data loading and processing |
| `pywebview` | Native desktop window (WebView2 on Windows) hosting the web UI |
| `wordfreq` | Real‑world word frequency (Zipf scale) |
| `pyinstaller` | (optional) Build standalone `.exe` |

---

## License & Credits

- 3Blue1Brown's Wordle analysis and original information‑theory approach.
- Word lists sourced from the [Kaggle Wordle dataset](https://www.kaggle.com/datasets/bcruise/wordle-valid-words/data).
- Code by Me, under the GNU General Public License v3.0 (GPLv3).
