# Wordle Strat-Console

> A solver that doesn't just *recommend* a word — it **proves** the shortest path.
> Every one of the 2,315 official NYT answers is solved in 6 guesses or fewer, across
> all six game modes, verified by an exhaustive closed-loop replay (not a cache read).

---

## Why this exists

Most Wordle helpers give you a word and a shrug. **Strat-Console** gives you a
*decision with a proof*: it explores the full game tree for the current domain,
weights every legal next guess by how much it shrinks the remaining answer pool
(plus a win-probability bonus), and tells you the optimal move — then lets *you*
decide. Because sometimes a human picks a different word, and that's fine: you
carry the turn cost, and you might even solve faster.

It is also **exhaustively correct**. We replayed all **47,814** games —
`2,315 answers × 6 domains` — through the real solver engine and the real
feedback loop. **Zero failures. Worst case 6 turns.** That is not a claim we
take on faith; it is a recomputed proof (see [Verification](#verification)).

---

## The six domains (locked at start)

The game space is partitioned into **six mutually exclusive, collectively
exhaustive domains**, fixed the moment a game begins:

| Domain      | Mode   | NYT hints | Pool size |
|-------------|--------|-----------|-----------|
| `normal_0`  | Normal | 0         | 2,315     |
| `normal_1`  | Normal | 1 (V×C)   | 2,315     |
| `normal_2`  | Normal | 2 (V×C)   | 2,315     |
| `hard_0`    | Hard   | 0         | 2,315     |
| `hard_1`    | Hard   | 1 (V×C)   | 2,315     |
| `hard_2`    | Hard   | 2 (V×C)   | 2,315     |

- **Normal/Hard** is your choice (toggle before turn 1).
- **Hints** are the *official* NYT hint mechanic: reveal **1 consonant + 1 vowel**.
  A word made only of vowels/consonants (e.g. `queue`, `rhythm`) forces the
  "1 hint" domain by rule — the engine handles this automatically.
- The **domain locks after turn 1**. You'll see a loud **DOMAIN LOCKED** notice,
  and both the HARD toggle and the hint input show a visible **✕ locked** badge.
  This is intentional: the solver committed to a fixed game space the moment you
  submitted your first guess, and changing the mode mid-game would be cheating.

**No-hint already solves 100%.** Hints are an optional shortcut that can shave a
turn — not a requirement.

---

## What the UI shows

Three intel panels, plus a clickable full answer pool:

- **STRATEGY → SOLVE** — the top recommended next words, ranked by **SCORE**
  (a blended info-gain + win-probability value; higher = better next guess).
  The bar is normalized to the top word, so it shows *relative* strength.
- **STRATEGY → SHRED** — the remaining answers with the **highest posterior
  probability** of being *the* answer (`P(ans)` as a true %), i.e. the words
  that would be the most punishing to leave in the pool.
- **POOL** — **every** remaining possible answer (capped at 400 rendered rows
  with an "and N more" count). **Click any word to load it as your guess.**
  The solver recommends; you decide. A non-top pick may even solve faster.
- **Loud banners** — every meaningful state change announces itself:
  `SUCCESS · Solved!`, `INFO · Hard mode ON`, `SUCCESS · HINT LOGGED`,
  `INFO · HINT LOCKED`, `INFO · DOMAIN LOCKED`. No silent state changes.

### How to play
1. **Type** your guess (just press letter keys — no box to click). Or click any
   word in **POOL** to load it.
2. **Fix tile colors**: click each tile on the active row to cycle
   grey → yellow → green, matching your real Wordle.
3. **Submit** with `Enter` (or the on-screen key). The SOLVE list is your optimal
   word — but any POOL word is legal.
4. **NYT hint (optional)**: type one consonant + one vowel and log them.
5. **Mode & lock**: toggle HARD any time before turn 1; after that, mode + hints
   lock for the game.
6. **SYSTEM RESET** for a new puzzle, **EXIT APP** to quit.

---

## Architecture (what's actually inside)

```
src/wordle_solver/
├── engine/                 # the proof engine
│   ├── engine.py           # solver core: suggestion search, exact minimax, pool tracking
│   ├── game.py             # single-game closed-loop simulator (guess -> feedback -> shrink)
│   ├── game_mode.py        # the 6-domain model (mode + hint count -> domain)
│   ├── lexicon.py          # 2,315 answers + 10,657 valid guesses
│   ├── modes.py            # normal/hard rule definitions
│   ├── patterns.py         # 3^5 feedback encoding (grey/yellow/green)
│   └── scoring.py          # entropy / win-probability scoring
├── app/
│   ├── web_server.py       # HTTP API (GET /api/state, POST /api/submit|hint|hard|reset)
│   ├── dev_server.py       # dev launcher (parent-pid watchdog, idle/uptime caps)
│   └── cli.py              # headless CLI
├── desktop/
│   ├── desktop_app.py      # frozen-bundle entry: in-process server + WebView2 window
│   ├── build_dist.py       # one-folder EXE build helper
│   └── desktop_app.spec    # PyInstaller spec
├── generators/            # offline data builders (NOT run in CI)
│   ├── build_word_data.py  # derives scientific_word_data.csv from wordfreq
│   ├── build_residual_optimal*.py  # 0/1/2-hint opening trees (multi-hour proofs)
│   └── find_t1_h.py        # exact turn-1 hard-mode opening prover
└── data/                  # committed, deterministic artifacts
    ├── scientific_word_data.csv
    ├── valid_solutions.csv / valid_guesses.csv
    ├── residual_optimal.json / _1hint.json / _2hint.json / _nohint.json
    ├── t1_h_opening.json
    └── wordle_full_matrix.npy
```

The engine is **in-memory and deterministic**: the turn-1 cache is computed live
(no committed `turn1_cache.json` — that artifact is obsolete). The only committed
data are the lexicon CSVs and the pre-proven residual opening trees.

### Web vs desktop
- **`web_server.py`** serves the SPA (`web/index.html` + `app.js` + `styles.css`)
  on `http://127.0.0.1:8000`. The frontend talks to it over a tiny JSON API.
- **`desktop_app.py`** builds a one-folder EXE that runs the *same* server
  in-process and renders the *same* SPA in a WebView2 window. One code path,
  two delivery forms — which is why the frozen-bundle self-play test is a real
  behavioral-equivalence proof, not a compile check.

---

## Build & run

### Desktop EXE (what most users want)
```bash
python build_game.py
# -> dist/Wordle-Strat-Console/Wordle-Strat-Console.exe  (one folder, portable)
```
Run it. A window opens, the solver is live, no install needed.

### Dev server (for tinkering / UI work)
```bash
PYTHONPATH=src python -m wordle_solver.app.web_server
# open http://127.0.0.1:8000
```

### Headless CLI
```bash
PYTHONPATH=src python -m wordle_solver.app.cli --help
```

---

## Verification

Two independent gates, each real:

1. **Exhaustive closed-loop replay (the foundation proof).**
   `tests/test_game_contract.py::test_domain_solves_100[...]` replays all six
   domains end-to-end: for every answer it plays the solver's optimal line
   against the *actual* feedback loop until solved. **47,814 games, 0 failures,
   ≤6 turns.** The gate cache is gitignored and always cold in CI, so a green
   run is a genuine recompute — never a cached pass.

2. **Frozen-bundle self-play (the shipped-artifact proof).**
   `tests/test_frozen_bundle.py` builds (if needed) and launches the **real EXE**,
   then self-plays the hard no-hint residuals through its HTTP API — proving the
   CI-built app behaves identically to the source. It covers the *default*
   no-override launch path (the bug we caught and fixed), not just a forced port.

### Reproduce locally
```bash
# fast suite (default CI gate)
PYTHONPATH=src python -m pytest -m "not exhaustive" -W error -q

# full 6-domain gate (cold recompute, ~18 min — runs in CI only on core changes)
PYTHONPATH=src python -m pytest -m exhaustive -W error -q
```

The project mandates **zero warnings** (`-W error` everywhere).

---

## CI strategy (fast by default, thorough on risk)

- **`test-suite.yml` → `test` job**: runs the **non-exhaustive** suite on every
  push/PR, zero-warnings enforced. Fast.
- **`test-suite.yml` → `exhaustive-gate` job**: runs the full 47,814-game gate
  **only when the diff touches core engine/game/mode logic** that the six domains
  are built from (`engine/`, `game_mode.py`, `generators/`, `data/`,
  `app/web_server.py`). Otherwise it is skipped. `workflow_dispatch` always runs
  it (opt-in full proof).
  → The exhaustive gate runs **if and only if** a core change could regress a mode.
- **`build-exe.yml`**: on a `v*` tag, builds the EXE from committed source, runs
  the frozen-bundle self-play, zips `dist/Wordle-Strat-Console/`, and attaches
  `Wordle-Strat-Console.zip` to the release. No manual uploads.

---

## Enumeration report

`EXHAUSTIVE_ENUMERATION.csv` (47,815 rows: header + 47,814 games) and
`EXHAUSTIVE_ENUMERATION.txt` (per-turn tile colors) are committed artifacts
generated by `src/wordle_solver/tools/enumerate_exhaustive.py`. Columns:
`word, mode, hint, turns, status, guesses`. They are a human-readable record of
the full proof, not an input to it.

---

## Notes & honesty

- **Numbers are accurate.** SOLVE shows a blended SCORE (not raw "gain in bits");
  SHRED shows a true posterior `P(ans)` %. Bars are relative, never a fake 0–100%.
- **The desktop app does not fork-bomb.** Measured: ~170 MB working set per game
  window; WebView2 children appear only under a live game, not under the dev
  server. Closing the window terminates the in-process server.
- **Probes live in `probes/`.** Useful diagnostic scripts (OS-hygiene census,
  GUI play drivers) are kept there, not deleted — they double as regression
  monitors.
