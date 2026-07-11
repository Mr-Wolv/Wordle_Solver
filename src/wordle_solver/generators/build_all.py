"""Build orchestrator: regenerate every data artifact the solver consumes.

Run:  python -m wordle_solver.generators.build_all

Order matters (each step's output feeds the next):
    1. build_word_data   -> scientific_word_data.csv  (deterministic; needs wordfreq)
    2. build_matrix      -> wordle_full_matrix.npy     (from the data above)
    3. find_t1_h         -> t1_h_opening.json          (multi-hour; prints best, writes file)
    4. build_residual_optimal -> residual_optimal.json (hard + hints residuals)
    5. build_nohint_tree -> residual_optimal_nohint.json (hard no-hint closure tree)

Steps 3 and 4/5 are expensive (hours / large search). Pass ``--quick`` to run
only the cheap, always-needed steps (1 and 2); the heavy artifacts are intended
to be committed baselines, not rebuilt on every machine.

Artifacts that are committed baselines (NOT rebuilt here by default):
    residual_optimal.json, residual_optimal_nohint.json, t1_h_opening.json
"""

from __future__ import annotations

import argparse
import runpy
import sys
import time


def _run(module: str, *extra_argv) -> None:
    print(f"\n=== {module} ===", flush=True)
    t0 = time.time()
    argv = [f"wordle_solver.generators.{module}", *extra_argv]
    runpy.run_module(argv[0], run_name="__main__")
    print(f"--- {module} done in {time.time()-t0:.1f}s ---", flush=True)


def main(quick: bool = False) -> None:
    # 1 + 2: always needed, cheap-ish (build_matrix runs in ~10s).
    _run("build_word_data")
    _run("build_matrix")

    if quick:
        print("\n[quick] skipping heavy artifacts "
              "(t1_h_opening.json / residual_optimal*.json are committed baselines)")
        return

    # 3: multi-hour brute-force prover for the best h-opening. Writes the file.
    _run("find_t1_h")
    # 4 + 5: residual trees (committed baselines).
    _run("build_residual_optimal")
    _run("build_nohint_tree")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="only rebuild word data + matrix; skip committed heavy artifacts")
    args = ap.parse_args()
    main(quick=args.quick)
