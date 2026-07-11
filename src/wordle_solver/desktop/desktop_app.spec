# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the desktop WebView2 app (wordle_solver.desktop.desktop_app).

The UI is a real DOM (web/) served by wordle_solver.app.web_server and hosted
inside a native pywebview window. pywebview bundles cleanly with PyInstaller
(unlike Flet, whose hook was broken). All runtime data is added so the frozen
exe finds it via wordle_solver.utils.resource_path (-> sys._MEIPASS).
"""

import os

# This spec lives at <repo>/src/wordle_solver/desktop/desktop_app.spec, so the
# repo root is two directories up from SPECPATH.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", "..", ".."))
APP = os.path.join(REPO_ROOT, "src", "wordle_solver", "desktop", "desktop_app.py")
ENTRY = os.path.join(SPECPATH, "..")  # package parent, for pathex

datas = [
    (os.path.join(REPO_ROOT, "web"), "web"),
    (os.path.join(REPO_ROOT, "scientific_word_data.csv"), "."),
    (os.path.join(REPO_ROOT, "wordle_full_matrix.npy"), "."),
    (os.path.join(REPO_ROOT, "valid_solutions.csv"), "."),
    (os.path.join(REPO_ROOT, "turn1_cache.json"), "."),
    (os.path.join(REPO_ROOT, "residual_optimal.json"), "."),
    (os.path.join(REPO_ROOT, "residual_optimal_nohint.json"), "."),
    (os.path.join(REPO_ROOT, "t1_h_opening.json"), "."),
    (os.path.join(REPO_ROOT, "icon.ico"), "."),
    (os.path.join(REPO_ROOT, "splash.html"), "."),
]

a = Analysis(
    [APP],
    pathex=[REPO_ROOT, os.path.join(REPO_ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "wordle_solver",
        "wordle_solver.app.web_server",
        "wordle_solver.app.cli",
        "wordle_solver.desktop.desktop_app",
        "wordle_solver.desktop.build_dist",
        "wordle_solver.engine.engine",
        "wordle_solver.engine.lexicon",
        "wordle_solver.engine.scoring",
        "wordle_solver.engine.patterns",
        "wordle_solver.engine.game",
        "wordle_solver.utils",
        "webview",
        "uvicorn",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Wordle-Strat-Console",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    splash=os.path.join(REPO_ROOT, "splash.bmp"),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO_ROOT, "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Wordle-Strat-Console",
)
