"""Wordle Strat-Console — entropy-driven, hint-aware Wordle solver.

Public surface:
    from wordle_solver.engine import WordleEngine, Lexicon, PatternMatrix
    from wordle_solver.engine import score_guesses, play_one_game
    from wordle_solver.app import web_server, cli
    from wordle_solver.desktop import desktop_app, build_dist

Layout (single import root `wordle_solver`):
    wordle_solver/
      utils.py            shared helpers (resource_path for PyInstaller)
      engine/             solver core (data, scoring, controller, game)
        lexicon.py        word/answer data + the 2315x2315 pattern matrix
        scoring.py        vectorized information-gain scoring
        engine.py         game state, hard-mode rule, hint pruning, caches
        patterns.py       canonical pattern math + shared minimax (single source)
        game.py           headless self-play (benchmarks/profiler/tests)
      app/                front-ends
        web_server.py     FastAPI backend (serves web/)
        cli.py            terminal solver
      desktop/            native wrapper + build recipe
        desktop_app.py    pywebview (WebView2) window
        build_dist.py     reproducible one-folder build
      generators/         offline artifact builders (not shipped at runtime)
"""

__version__ = "2.1.0"

from .engine import WordleEngine, Lexicon, PatternMatrix, score_guesses, play_one_game

__all__ = [
    "WordleEngine",
    "Lexicon",
    "PatternMatrix",
    "score_guesses",
    "play_one_game",
    "__version__",
]
