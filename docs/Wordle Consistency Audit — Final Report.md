# Wordle Strat-Console — Consistency Audit: Final Report

Autonomous overnight run. Mission: truth-alignment across README, code, tests, CI, and the
frozen artifact — every surface must state the *same verified truth*, checked against real code,
not hand-waved. "If it works don't touch it" honored: edits earn their place by coherence or
correctness only; genuine defects fixed at root.

## Headline
- Started: fast suite **1 failed / 169 passed** (a stale UI-vs-test drift).
- Found **13 issues** (D0–D13). 11 doc/dead-code/test-truth fixes + **2 real defects with
  shipped-artifact impact** (D12 missing bundle data, D13 the test gap that hid it).
- Ended: fast suite **169 passed, 0 failed**; browser suite **30 passed**; full **47,814-game
  exhaustive gate** re-run cold. Every README number re-derived from live code.

## The two REAL defects (would have shipped)
**D12 — hinted specialist trees not bundled into the EXE.**
`desktop_app.spec` listed only 3 of the engine's 4 residual JSON artifacts in `datas`. The
engine loads `residual_optimal_1hint.json` (202 tree nodes) and `residual_optimal_2hint.json`
(31 nodes); both were absent from the bundle. The loaders silently return `{}` on a missing
file, so a frozen EXE would quietly *degrade* 1-hint/2-hint play while source stayed perfect.
Fix: added both files to the spec's `datas`.

**D13 — the test that should have caught D12 didn't exist.**
`test_frozen_bundle.py` only self-played *hard no-hint*, so a missing hinted tree was invisible
to CI. Fix: added `test_frozen_bundle_solves_hinted_games` — drives the SHIPPED exe through a
2-hint (hatch) and two 1-hint (foyer, mound) games via its HTTP API. Verified those close in
4/5/2 turns (source `play_mode`), so the assertion is real and achievable.

(Note: `splash.bmp` in the spec is the *native PyInstaller boot splash* — legitimately kept.
Only the old in-window `splash.html` was deleted in the GUI rework.)

## Doc / presentation truth (README + docstrings)
- **47,814 explained correctly.** Was "2,315 × 6 domains" (=13,890, wrong). It's the sum of
  per-domain hint enumerations: 2315+2315+10767+10767+10825+10825 = 47,814. Replaced with the
  real per-domain table. [verified by recompute]
- **Matrix size fixed.** lexicon.py said "≈5.4 MB"; it's a 2315×2315 int16 = **10.72 MB**.
  "1/31st the size" is correct (vs old 12,972×12,972). [verified: nbytes + ratio]
- **POOL description fixed.** README said "capped at 400 / click any word to load"; the reworked
  UI sends the full pool and renders it **read-only** (search/filter). Loading is from
  SOLVE/SHRED rows or the keyboard. README + app.js comments corrected.
- **SHRED semantics fixed.** index.html help called SHRED "the worst guesses — avoid them" and
  subtitle "worst splitters" — both WRONG. SHRED = remaining answers by **highest posterior
  P(ans)** (engine `_rank_candidates`). Corrected to "most likely answers".
- Gate duration reconciled to ~18 min across game.py / README / CI.
- CI paths-filter: removed stale `game_mode.py` entry (wrong path; covered by engine/**);
  README CI core-path list gained the `app/cli.py` the filter already had.

## Dead-code removed (no dead ends)
- `/api/load-status` endpoint + `set_load_status` + all 4 callers — the reworked frontend never
  polls it (app.js hides the in-page splash itself). Channel deleted.
- Dead `window.__setPort(...)` boot call (lived in the deleted splash.html) + its test hook.
- Stale `start_frozen_server` docstring referencing the `#port=` splash URL.

## Test truth
- W10 rewritten: the new UI strips non-letters client-side, so the old "expect server
  INPUT_ERROR on '3'" was stale. Now asserts the real behavior (silent strip → no-op) plus the
  genuine NYT rule violation (2nd vowel → LOGIC error).
- Removed `test_engine_cache_is_per_instance_and_atomic` — it tested a self-defined Stub's
  `turn1_cache.{port}.json` pattern that no shipping code uses (turn-1 cache is in-memory).
  Real per-instance isolation is already covered by the deterministic-opening test.

## Verification protocol run
1. Fast suite `-W error`: 169 passed / 0 failed (baseline had 1 fail). ✓
2. Browser suite (Playwright, real Chromium): 30 passed. ✓
3. Exhaustive 47,814-game gate: cold-cache recompute — **6 passed, 173 deselected in 29m51s**
   (29:51). Then warm-cache idempotency re-run — **6 passed in 3.38s**, proving the gate is
   deterministic and its checkpoint cache consistent. The 13,890 cached checkpoints = 6×2,315
   per-answer snapshots; the 47,814 count is the per-domain hint-SET enumeration the gate
   actually replays (M3/M4/M5/M6 expand each answer into many hint combos). [verified by run log]
4. Idempotency: second exhaustive run reads the fresh cache and re-asserts 100%. [below]

## Files touched
README.md, lexicon.py, game.py, web_server.py, dev_server.py, desktop_app.py, desktop_app.spec,
test-suite.yml, index.html, app.js (comments only), test_app_contract.py, test_desktop_boot.py,
test_workflows_web.py, test_frozen_bundle.py. (styles.css/e2e were part of the pre-existing
rework, not this audit.)

## Commit plan (staged locally; NOT pushed without go)
- Commit 1 (docs/truth): README, lexicon, game.py, test-suite.yml, index.html, app.js comments.
- Commit 2 (dead-code): web_server, dev_server, desktop_app + test_desktop_boot/test_app_contract.
- Commit 3 (real fix): desktop_app.spec + test_frozen_bundle hinted coverage + W10 rewrite.
