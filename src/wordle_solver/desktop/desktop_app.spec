# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the desktop WebView2 app (wordle_solver.desktop.desktop_app).

The UI is a real DOM (web/) served by wordle_solver.app.web_server and hosted
inside a native pywebview window. pywebview bundles cleanly with PyInstaller
(unlike Flet, whose hook was broken). All runtime data is added so the frozen
exe finds it via wordle_solver.utils.resource_path (-> sys._MEIPASS).
"""

import os

# This spec lives at <repo>/src/wordle_solver/desktop/desktop_app.spec.
# SPECPATH = <repo>/src/wordle_solver/desktop ; three ".." land on <repo>.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", "..", ".."))
PKG = os.path.join(REPO_ROOT, "src", "wordle_solver")  # the import package
DATA = os.path.join(PKG, "data")
ASSETS = os.path.join(PKG, "assets")
WEB = os.path.join(PKG, "web")
APP = os.path.join(PKG, "desktop", "desktop_app.py")
# pathex must let PyInstaller import the `wordle_solver` package.
pathex_root = os.path.join(REPO_ROOT, "src")

datas = [
    (WEB, "web"),
    (os.path.join(DATA, "scientific_word_data.csv"), "data"),
    (os.path.join(DATA, "wordle_full_matrix.npy"), "data"),
    (os.path.join(DATA, "valid_solutions.csv"), "data"),
    # NOTE: turn-1 openings are cached IN-MEMORY only by the engine (see
    # engine._load_turn1_cache); there is no turn1_cache.json artifact to
    # bundle. Do not add one here or the build breaks on a clean checkout.
    (os.path.join(DATA, "residual_optimal.json"), "data"),
    (os.path.join(DATA, "residual_optimal_nohint.json"), "data"),
    (os.path.join(DATA, "residual_optimal_1hint.json"), "data"),
    (os.path.join(DATA, "residual_optimal_2hint.json"), "data"),
    (os.path.join(DATA, "t1_h_opening.json"), "data"),
    (os.path.join(ASSETS, "icon.ico"), "assets"),
]

a = Analysis(
    [APP],
    pathex=[pathex_root],
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
    splash=os.path.join(ASSETS, "splash.bmp"),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ASSETS, "icon.ico"),
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
