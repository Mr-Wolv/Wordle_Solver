# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the desktop WebView2 app (desktop_app.py).

The UI is a real DOM (web/) served by web_server.py and hosted inside a
native pywebview window. pywebview bundles cleanly with PyInstaller
(unlike Flet, whose hook was broken). All runtime data is added so the
frozen exe finds it via utils.resource_path (-> sys._MEIPASS).
"""

import os

ROOT = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "scientific_word_data.csv"), "."),
    (os.path.join(ROOT, "wordle_full_matrix.npy"), "."),
    (os.path.join(ROOT, "valid_solutions.csv"), "."),
    (os.path.join(ROOT, "turn1_cache.json"), "."),
    (os.path.join(ROOT, "residual_optimal.json"), "."),
    (os.path.join(ROOT, "t1_h_opening.json"), "."),
    (os.path.join(ROOT, "icon.ico"), "."),
    (os.path.join(ROOT, "splash.html"), "."),
]

a = Analysis(
    [os.path.join(ROOT, "desktop_app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "web_server",
        "webview",
        "uvicorn",
        "engine",  # referenced via Engine import in web_server
        "lexicon",
        "scoring",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# One-FOLDER build: the EXE stays small and the binaries/data live in a
# sibling folder, so there is NO 65 MB in-memory unpack on launch — the
# window (and splash) appears in ~1 s instead of hanging ~7 s. The previous
# spec inlined a.binaries/a.datas into EXE, which makes a one-FILE bundle.
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
    splash=os.path.join(ROOT, "splash.bmp"),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "icon.ico"),
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
