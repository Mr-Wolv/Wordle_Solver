# Wordle Strat-Console — Repo-Wide Consistency Audit

Autonomous overnight run. Tags: **[logic]** = read code / ran it; **[x-check]** = assumption+cross-check.
Truth source = actual shipped code behavior (working tree = what ships).
Repo: `D:\Wordle_Solver` · Branch `main` · 9 files modified (major GUI rework, uncommitted).
Vault note lives in `D:\Lunar Novel` (primary `Obsidian Vault` is a dehydrated OneDrive placeholder, writes ENOENT).

## Baseline test state [logic]
`pytest -m "not exhaustive" -W error` → **1 failed, 169 passed, 3 skipped, 6 deselected** (146s).
FAIL = `test_workflows_web.py::test_W10_hint_violations` (D6).

## Ground-truth numbers (measured) [logic]
| Quantity | Value | Source |
|---|---|---|
| NYT answers | 2,315 | valid_solutions.csv / Lexicon.n_solutions |
| Full dictionary | 12,972 | scientific_word_data.csv / Lexicon.n_all |
| Extra valid guesses | 10,657 | valid_guesses.csv (2315+10657=12972 ✓) |
| Pattern matrix | 2315×2315 int16 = **10.72 MB** | measured nbytes |
| Feedback patterns | 3^5 = 243 | scoring.N_PATTERNS |
| Exhaustive games | **47,814** ✓ | = 2315+2315+10767+10767+10825+10825 (per-domain hint enumeration), NOT 2315×6 |

## DEFECTS (all [logic])
- **D0** README:19 says "47,814 = 2,315 × 6 domains" but 2315×6=13,890. Number 47,814 is CORRECT; the *explanation* is wrong. Fix to the real per-domain breakdown.
- **D1** CRIT lexicon.py:5 matrix "≈5.4 MB" → real 10.72 MB; "1/31st / 31×" stale.
- **D2** CRIT README:55,63-65,71 POOL "clickable / capped at 400 / click any word to load" → working tree sends FULL pool, renders read-only (aria-disabled, no click). Load happens from SOLVE/SHRED rows only.
- **D3** CRIT/UI SHRED = highest-posterior remaining answers (engine `_rank_candidates`). index.html:61 "worst splitters" + :128 "worst guesses… avoid them" are WRONG. README/tooltip correct.
- **D4** WARN app.js:379-380 "clickable to load" contradicts read-only render; :439 "used by the POOL card" stale.
- **D5** DEAD desktop_app.py:262 `__setPort` call (splash.html deleted; window now uses load_url) — guarded/harmless but dead; test_desktop_boot fake-window captures it (dead scaffold). `start_frozen_server` docstring stale re #port=.
- **D6** TEST-DRIFT test_W10 expects server INPUT_ERROR on hint "3", but app.js:70,504 strips non-letters client-side → no-op. Test is stale vs the (better) new UI.
- **D7** DEAD `/api/load-status` + `set_load_status` (web_server 341-347) called by dev_server:184/190 + desktop_app:198/204 during boot, but app.js:253 confirms frontend never polls it. Dead channel.
- **D8** DOC game.py:42 gate "~15-minute" vs README:174 + test-suite.yml:5 "~18 min" — pick one (18 is CI's stated figure).
- **D9** CI test-suite.yml:43 paths-filter lists `src/wordle_solver/game_mode.py` (wrong path; real file is engine/game_mode.py, already covered by engine/**). Stale/redundant filter line.
- **D10** TEST-WEAK test_app_contract.py:4 docstring names deleted splash.html; `test_engine_cache_is_per_instance_and_atomic` tests a local Stub's `turn1_cache.{port}.json` pattern that NO shipping code uses (engine turn1 cache is in-memory no-op). Asserts a fiction.
- **D11** egg-info NOT tracked (gitignored) but present on disk with stale PKG-INFO (splash.html, turn1_cache.json). Local artifact only — no repo impact; leave.
- **D12** ⚠ REAL SHIPPED-ARTIFACT BUG [logic]: `desktop_app.spec` datas bundled only 3 of the engine's data JSONs — MISSING `residual_optimal_1hint.json` (202 tree entries) and `residual_optimal_2hint.json` (31 entries). Loaders silently return {} when a file is absent, so the FROZEN exe would degrade 1-hint/2-hint play (source is fine; only the bundle). NOTE splash.bmp in spec is the PyInstaller NATIVE boot splash (legit, kept) — distinct from the deleted in-window splash.html. FIXED: added both to spec datas.
- **D13** TEST-GAP that hid D12 [logic]: `test_frozen_bundle.py` only self-played hard NO-HINT, so the missing hinted trees were invisible to CI. FIXED: added `test_frozen_bundle_solves_hinted_games` (2-hint hatch, 1-hint foyer/mound) driven through the shipped exe's HTTP API; verified those solve in 4/5/2 turns via source play_mode.

## FIX PLAN (root-cause, coherent batches)
Batch A — doc/comment truth (zero wiring risk): D0, D1, D2, D3(README+index.html), D4, D8, D9, test_app_contract docstring.
Batch B — dead-code removal (mandate: no dead ends): D5 (__setPort + fake-window hook), D7 (load-status channel), D10 stale test. Verify with full suite after.
Batch C — test truth: D6 rewrite to assert new client-strip behavior.
Then: README infographic re-derive; final full 47,814 exhaustive gate + idempotency re-run.

## Verification protocol
1. `pytest -m "not exhaustive" -W error -q` green after each batch.
2. Full `pytest -W error` (incl. exhaustive) at end; re-run for cache idempotency.
3. Adversarial: re-inject a fixed lie, confirm the aligned test/doc catches it, restore.
