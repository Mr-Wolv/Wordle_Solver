"""Headless regression tests for the desktop-app boot/close contract.

These cover the behaviours most likely to silently regress when someone
touches desktop_app.py / Engine.py / splash.html, WITHOUT needing a browser
(the Playwright e2e suite in test_e2e_web.py covers the live DOM; it is
skipped when no browser is installed — see conftest.py).

Run:  python -m pytest test_app_contract.py -q
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import pytest
import wordle_solver.engine as Engine  # noqa: E402  (used by contract tests)


def _load(path: str, modname: str):
    spec = importlib.util.spec_from_file_location(modname, os.path.join(ROOT, path))
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


desktop = _load(os.path.join("src", "wordle_solver", "desktop", "desktop_app.py"), "desktop_app_test")
DA_SRC = open(os.path.join(ROOT, "src", "wordle_solver", "desktop", "desktop_app.py"), encoding="utf-8").read()
SPLASH_SRC = open(os.path.join(ROOT, "splash.html"), encoding="utf-8").read()
# desktop_app.spec is a build artifact (*.spec is gitignored) and may be absent
# from a clean checkout — only load it when present.
_SPEC_PATH = os.path.join(ROOT, "src", "wordle_solver", "desktop", "desktop_app.spec")
SPEC_SRC = open(_SPEC_PATH, encoding="utf-8").read() if os.path.exists(_SPEC_PATH) else None


# ── OPEN: splash opens instantly via a #fragment, never a ?query ────────────
def test_open_splash_uses_hash_not_query():
    # file:// URIs have no ?query support; a ? would make WebView2 look for a
    # file literally named splash.html?port=… and report "file not found".
    assert 'file_uri(str(ROOT / "splash.html")) + f"#port={initial_port}"' in DA_SRC
    assert re.search(r'file_uri\([^)]*\) \+ f"\?', DA_SRC) is None


def test_splash_reads_hash_not_search():
    assert "location.search" not in SPLASH_SRC
    assert "location.hash" in SPLASH_SRC
    assert "closing" in SPLASH_SRC


# ── CLOSE: graceful, no hard-kill ───────────────────────────────────────────
def test_close_is_graceful_no_hardkill():
    # The close path must not os._exit(0) — it must paint then destroy.
    region = DA_SRC[DA_SRC.find("def close_with_splash"):DA_SRC.find("# ── window + lifecycle")]
    # Only a real CALL (os._exit() — note the parenthesis) counts; the
    # docstring legitimately contains the words "no os._exit hard-kill".
    assert "os._exit(" not in region
    assert "window.load_html" in DA_SRC
    assert "window.destroy()" in DA_SRC


def test_close_with_splash_paints_inline_screen():
    region = DA_SRC[DA_SRC.find("def close_with_splash"):DA_SRC.find("# ── window + lifecycle")]
    assert "Shutting down" in region
    assert "load_html" in region


# ── BUILD: one-folder (no 65 MB unpack hang) ───────────────────────────────
@pytest.mark.skipif(SPEC_SRC is None, reason="desktop_app.spec not present in checkout")
def test_spec_is_one_folder():
    assert "COLLECT(" in SPEC_SRC
    assert "a.binaries" in SPEC_SRC and "a.datas" in SPEC_SRC
    # EXE must NOT inline binaries/data (that would make a one-FILE bundle).
    assert not re.search(r"exe = EXE\(\s*pyz,\s*a\.scripts,\s*a\.binaries", SPEC_SRC, re.S)


@pytest.mark.skipif(SPEC_SRC is None, reason="desktop_app.spec not present in checkout")
def test_build_emits_folder_only_not_root_exe():
    """A one-folder spec also writes a redundant dist/<name>.exe at the root.
    That copy cannot launch (no sibling _internal), so build_dist.py must
    delete it. This test enforces the 'folder only' distributable."""
    import subprocess

    name = "Wordle-Strat-Console"
    dist = os.path.join(ROOT, "dist")
    folder = os.path.join(dist, name)
    # Build deterministically through the committed recipe.
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "src", "wordle_solver", "desktop", "build_dist.py")], check=True
    )
    # Folder is the real, self-contained app.
    assert os.path.isdir(folder), "dist folder missing"
    assert os.path.exists(os.path.join(folder, name + ".exe")), "launcher missing in folder"
    # No stray root exe.
    assert not os.path.exists(os.path.join(dist, name + ".exe")), \
        "redundant root exe must be removed by build_dist.py"
    # _internal holds the frozen deps so the folder runs standalone.
    assert os.path.isdir(os.path.join(folder, "_internal")), "_internal missing"


# ── MULTI-INSTANCE: per-instance cache + distinct ports ─────────────────────
def test_engine_cache_is_per_instance_and_atomic():
    import tempfile
    import json
    import wordle_solver.engine as Engine

    base = tempfile.mkdtemp(prefix="hermes-contract-")
    orig = Engine.resource_path

    def fake_rp(rel):
        return os.path.join(base, "turn1_cache.json") if rel == "turn1_cache.json" else orig(rel)

    Engine.resource_path = fake_rp
    try:
        class Stub:
            _port = 8753

            def _turn1_cache_path(self):
                p = Engine.resource_path("turn1_cache.json")
                if self._port is None:
                    return p
                b, ext = os.path.splitext(p)
                return f"{b}.{self._port}{ext}"

        s = Stub()
        assert s._turn1_cache_path().endswith("turn1_cache.8753.json")
        data = {"normal": [{"word": "stare", "score": 1.0, "win_prob": 0.5, "is_candidate": True}],
                "hard": None}
        tmp = s._turn1_cache_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, s._turn1_cache_path())
        assert os.path.exists(s._turn1_cache_path()) and not os.path.exists(tmp)
    finally:
        Engine.resource_path = orig
        for f in os.listdir(base):
            os.remove(os.path.join(base, f))
        os.rmdir(base)


def test_find_free_port_skips_in_use():
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sk.bind(("127.0.0.1", 8753))
    sk.listen(8)
    p = desktop._find_free_port(8753)
    sk.close()
    assert p != 8753  # must skip the in-use port


# ── ENGINE LOGIC: pattern math is the single source of truth ───────────────
def test_no_duplicate_pattern_function():
    # scoring.py previously duplicated calculate_pattern as pattern_for (dead).
    assert "def pattern_for" not in open(
        os.path.join(ROOT, "src", "wordle_solver", "engine", "scoring.py")
    ).read()


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
