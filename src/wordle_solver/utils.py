"""Shared utilities for the Wordle solver."""


def resource_path(relative_path: str) -> str:
    """Get absolute path to a resource, working for dev and for PyInstaller.

    In dev (and in the test suite) this resolves against the current working
    directory. In a frozen one-folder bundle, ``sys._MEIPASS`` points at the
    bundle's ``_internal`` directory, where the spec's ``datas`` are copied.

    Stray per-instance turn-1 caches (``turn1_cache.<port>.json``) are dev
    artifacts written by the engine's multi-instance logic; they must never be
    resolved as the canonical ``turn1_cache.json``. When a *suffixed* cache
    name is requested we still return it as-is (the engine manages the suffix)
    but we never treat it as the committed baseline.
    """
    import os
    import sys

    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
