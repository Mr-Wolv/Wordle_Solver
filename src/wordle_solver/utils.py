"""Shared utilities for the Wordle solver.

Resource resolution
-------------------
``resource_path`` (kept for backward compatibility) and the typed
helpers ``data_path`` / ``assets_path`` / ``web_path`` resolve bundled
files in a way that is **machine- and cwd-independent**:

* In a frozen PyInstaller bundle the files live under ``sys._MEIPASS``
  (the ``_internal`` directory), which is where the spec's ``datas`` are
  copied.
* In source / editable installs the files live inside the package
  (``src/wordle_solver/{data,assets,web}``), so we resolve relative to
  ``__file__`` of this module — **never the current working directory**.

The previous implementation resolved against ``os.path.abspath(".")``, which
meant the app only worked when launched from the repo root. That broke for
cloners, CI, and the frozen bundle's startup. The new resolvers use
the package location, so the same code works everywhere.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# Package root = src/wordle_solver/  (this file lives directly under it).
_PKG = Path(__file__).resolve().parent


def _base() -> Path:
    """Bundle-aware base directory for all bundled assets."""
    try:
        # Frozen one-folder bundle: sys._MEIPASS points at the folder
        # that contains data/, assets/, web/ (the spec's datas targets).
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    except Exception:
        return _PKG


def data_path(relative_path: str) -> str:
    """Absolute path to a bundled *data* artifact (CSV/npy/json)."""
    return str(_base() / "data" / relative_path)


def assets_path(relative_path: str) -> str:
    """Absolute path to a bundled *asset* (icon, splash, ...)."""
    return str(_base() / "assets" / relative_path)


def web_path(relative_path: str) -> str:
    """Absolute path to a bundled *web* frontend file (index.html, ...)."""
    return str(_base() / "web" / relative_path)


def find_free_port(preferred: int = 0, max_attempts: int = 50) -> int:
    """Return a free 127.0.0.1 TCP port, scanning up from ``preferred``.

    A port of 0 means "any free port" (the OS assigns one — we read back the
    actual number via ``getsockname``). This is the single source of truth
    for conflict-free binding so the dev server and the desktop wrapper never
    fight over a hardcoded port — and never leave a zombie process that holds
    the (memory-mapped) matrix file open.
    """
    for off in range(max_attempts):
        p = preferred + off
        if p > 65535:
            break
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                # port 0 → kernel picks a free one; report the real assignment
                return s.getsockname()[1] if p == 0 else p
            except OSError:
                continue
    raise RuntimeError(
        f"no free localhost port found near {preferred} "
        f"(tried {max_attempts} ports)"
    )


def resource_path(relative_path: str) -> str:
    """Backward-compatible resolver.

    Files are now namespaced under ``data/``, ``assets/`` or ``web/``
    inside the package, so callers should prefer the typed helpers above.
    For compatibility, a bare filename is resolved from the data directory.
    """
    p = Path(relative_path)
    if p.parent == Path("."):
        # Bare name -> assume a data artifact (the historical default).
        return data_path(relative_path)
    return str(_base() / relative_path)


# Convenience constants for the well-known artifacts.
MATRIX_FILE = "wordle_full_matrix.npy"
SOLUTIONS_FILE = "valid_solutions.csv"
WORDS_FILE = "scientific_word_data.csv"
