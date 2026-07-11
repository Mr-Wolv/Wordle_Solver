"""Offline artifact generators (NOT imported at runtime by the solver).

These rebuild the data artifacts the engine consumes:
    valid_solutions.csv / valid_guesses.csv  (source data, committed)
    scientific_word_data.csv                 (build_word_data)
    wordle_full_matrix.npy                   (build_matrix)
    residual_optimal.json                    (build_residual_optimal)
    residual_optimal_nohint.json             (build_nohint_tree)
    t1_h_opening.json                         (find_t1_h)
Run ``python -m wordle_solver.generators.build_all`` to rebuild everything
from the committed source CSVs in deterministic order.
"""
