"""Headless regression tests for the desktop-app boot/close contract.

These cover the behaviours most likely to silently regress when someone
touches desktop_app.py / the engine / the web frontend, WITHOUT needing a
browser (the Playwright e2e suite in test_e2e_web.py covers the live DOM; it
is skipped when no browser is installed — see conftest.py).

Run:  python -m pytest test_app_contract.py -q
"""
from __future__ import annotations
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
# repo root = parent of tests/
REPO_ROOT = os.path.dirname(ROOT)
sys.path.insert(0, REPO_ROOT)

import pytest
import wordle_solver.engine as Engine  # noqa: E402  (used by contract tests)

def _load(path: str, modname: str):
    spec = importlib.util.spec_from_file_location(modname, os.path.join(REPO_ROOT, path))
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


desktop = _load(os.path.join("src", "wordle_solver", "desktop", "desktop_app.py"), "desktop_app_test")
with open(os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "desktop_app.py"), encoding="utf-8") as fh:
    DA_SRC = fh.read()
with open(os.path.join(REPO_ROOT, "src", "wordle_solver", "web", "index.html"), encoding="utf-8") as fh:
    INDEX_SRC = fh.read()
with open(os.path.join(REPO_ROOT, "src", "wordle_solver", "web", "app.js"), encoding="utf-8") as fh:
    APPJS_SRC = fh.read()
# desktop_app.spec is a build artifact (*.spec is gitignored) and may be absent
# from a clean checkout — only load it when present.
_SPEC_PATH = os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "desktop_app.spec")
SPEC_SRC = None
if os.path.exists(_SPEC_PATH):
    with open(_SPEC_PATH, encoding="utf-8") as fh:
        SPEC_SRC = fh.read()


# ── OPEN: boot splash is an IN-PAGE overlay, dismissed by JS (no file/route) ──
def test_open_has_inpage_splash_overlay():
    # The boot splash is part of index.html (id="splash"), shown by default and
    # hidden by app.js once the UI is live — there is no second page/route to
    # swipe or navigate to (kills the old "splash is a chrome tab" bug).
    assert 'id="splash"' in INDEX_SRC
    assert 'id="closing"' in INDEX_SRC
    # app.js hides the splash (no dependence on a non-existent /api/load-status).
    assert "_hideSplash" in APPJS_SRC
    assert "this._hideSplash()" in APPJS_SRC


# ── CLOSE: graceful, in-page overlay, no hard-kill ──────────────────────────
def test_close_is_graceful_no_hardkill():
    # The close path must not os._exit(0) — it must paint then destroy.
    region = DA_SRC[DA_SRC.find("def close_with_splash"):DA_SRC.find("# ── window + lifecycle")]
    # Only a real CALL (os._exit( — note the parenthesis) counts; the docstring
    # legitimately contains the words "no os._exit hard-kill".
    assert "os._exit(" not in region
    # Close uses the in-page closing overlay, NOT a navigation/load_html.
    assert "window.__showClosing" in DA_SRC
    assert "window.destroy()" in DA_SRC
    # The teardown runs on the GUI thread via the deferred request_close hook.
    assert "request_close" in DA_SRC


def test_close_with_splash_paints_inline_screen():
    region = DA_SRC[DA_SRC.find("def close_with_splash"):DA_SRC.find("# ── window + lifecycle")]
    # The closing overlay is painted via the in-page __showClosing hook (not a
    # chrome navigation that would re-enable swipe-back).
    assert "window.__showClosing" in region
    assert "load_html" not in region


# ── BUILD: one-folder (no 65 MB unpack hang) ───────────────────────────────
@pytest.mark.skipif(SPEC_SRC is None, reason="desktop_app.spec not present in checkout")
def test_spec_is_one_folder():
    assert SPEC_SRC is not None
    assert "COLLECT(" in SPEC_SRC
    assert "a.binaries" in SPEC_SRC and "a.datas" in SPEC_SRC
    # EXE must NOT inline binaries/data (that would make a one-FILE bundle).
    assert not re.search(r"exe = EXE\(\s*pyz,\s*a\.scripts,\s*a\.binaries", SPEC_SRC, re.S)


# The full one-folder build is a heavy (multi-minute) native PyInstaller run
# that is environment-fragile (it shells out to the bundler and can hit
# intermittent AV/resource failures). The contract it checks (a redundant
# root EXE is removed, leaving the self-contained folder) is therefore
# verified ONLY when explicitly opted in via WS_BUILD_TEST=1 (e.g. a dedicated
# CI build job), keeping the default test run fast and deterministic. The
# spec-level test above still proves the recipe is a one-folder COLLECT.
_BUILD_OPT_IN = os.environ.get("WS_BUILD_TEST") == "1"


@pytest.mark.skipif(not _BUILD_OPT_IN,
                    reason="set WS_BUILD_TEST=1 to run the heavy PyInstaller build test")
@pytest.mark.skipif(SPEC_SRC is None, reason="desktop_app.spec not present in checkout")
def test_build_emits_folder_only_not_root_exe():
    """A one-folder spec also writes a redundant dist/<name>.exe at the root.
    That copy cannot launch (no sibling _internal), so build_dist.py must
    delete it. This test enforces the 'folder only' distributable."""
    import shutil
    # Clean up any previous build artifacts to avoid permission issues on Windows
    dist_dir = os.path.join(REPO_ROOT, "dist")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir, ignore_errors=True)

    import subprocess

    name = "Wordle-Strat-Console"
    dist = os.path.join(REPO_ROOT, "dist")
    folder = os.path.join(dist, name)
    # Build deterministically through the committed recipe.
    subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "build_dist.py")], check=True
    )
    # Folder is the real, self-contained app.
    assert os.path.isdir(folder), "dist folder missing"
    assert os.path.exists(os.path.join(folder, name + ".exe")), "launcher missing in folder"
    # No stray root exe.
    assert not os.path.exists(os.path.join(dist, name + ".exe")), \
        "redundant root exe must be removed by build_dist.py"
    # _internal holds the frozen deps so the folder runs standalone.
    assert os.path.isdir(os.path.join(folder, "_internal")), "_internal missing"


# ── MULTI-INSTANCE: per-instance engine state + distinct ports ─────────────
def test_engine_turn1_cache_is_per_instance_and_deterministic():
    """The turn-1 opening is cached IN-MEMORY, keyed by hint set, and is
    isolated per engine instance. Two independent engines must produce the
    SAME deterministic opening for the same hint state (no cross-instance
    leakage, no dependence on import/run order), and a forced hint set must
    change the opening without leaking into another instance's cache.
    """
    from wordle_solver.engine import WordleEngine

    e1 = WordleEngine()
    e2 = WordleEngine()
    # Both start at normal_0 with no hints -> identical, deterministic opening.
    s1, _ = e1.get_suggestions()
    s2, _ = e2.get_suggestions()
    assert [d["word"] for d in s1] == [d["word"] for d in s2]
    # Second call hits the in-memory cache and is still identical.
    s1b, _ = e1.get_suggestions()
    assert [d["word"] for d in s1b] == [d["word"] for d in s1]

    # A separate hint state produces a (possibly) different opening but only
    # for that engine; e2 (still no-hint) is unaffected.
    e1.add_hint("e")
    s1h, _ = e1.get_suggestions()
    s2b, _ = e2.get_suggestions()
    assert [d["word"] for d in s2b] == [d["word"] for d in s2]
    assert "e" in s1h[0]["word"]


def test_find_free_port_skips_in_use():
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sk.bind(("127.0.0.1", 8753))
    sk.listen(8)
    p = desktop.find_free_port(8753)
    sk.close()
    assert p != 8753  # must skip the in-use port
    assert 1 <= p <= 65535
    # the returned port must actually be bindable afterwards
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", p))


# ── ENGINE LOGIC: pattern math is the single source of truth ───────────────
def test_no_duplicate_pattern_function():
    # scoring.py previously duplicated calculate_pattern as pattern_for (dead).
    with open(
        os.path.join(REPO_ROOT, "src", "wordle_solver", "engine", "scoring.py")
    ) as fh:
        src = fh.read()
    assert "def pattern_for" not in src


def test_engine_pattern_matches_matrix():
    import numpy as np
    e = Engine.WordleEngine()
    W = e.lex.solution_words
    sol_idx = e.lex.solution_idx
    import random
    random.seed(2)
    for _ in range(300):
        g = random.choice(e.lex.all_words)
        s = random.choice(W)
        a = e.calculate_pattern(g, s)
        gi = e.word_to_idx[g]
        sai = int(np.nonzero(sol_idx == e.word_to_idx[s])[0][0])
        if e.solution_mask[gi]:
            ai = int(np.nonzero(sol_idx == gi)[0][0])
            b = int(e.pm.matrix[ai, sai])
        else:
            b = int(e.pm.row_for(g, np.array([sai]))[0])
        assert a == b
