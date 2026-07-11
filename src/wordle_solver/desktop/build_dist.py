"""Reproducible one-folder build for Wordle-Strat-Console.

Run:  python build_dist.py

Why this script exists (not just `pyinstaller desktop_app.spec`):
A PyInstaller one-folder spec (EXE + COLLECT) writes the launcher to
BOTH places:
  - dist/Wordle-Strat-Console/Wordle-Strat-Console.exe   (real app, with _internal)
  - dist/Wordle-Strat-Console.exe                         (redundant root copy)
The root copy is dead weight: there is no `_internal` next to it, so it
cannot launch on its own. We delete it so the distributable is the folder
ONLY, exactly what the user ships. Without this step the root exe keeps
"coming back" on every rebuild.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "Wordle-Strat-Console"
SPEC = os.path.join(ROOT, "desktop_app.spec")
# Build into the repo-root dist/ (not nested under src/).
DIST = os.path.abspath(os.path.join(ROOT, "..", "..", "..", "dist"))


def main():
    if not os.path.exists(SPEC):
        sys.exit(f"spec not found: {SPEC}")
    # Build the one-folder bundle.
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC],
        check=True,
    )
    # Remove the redundant root launcher; the real app is dist/<NAME>/.
    root_exe = os.path.join(DIST, NAME + ".exe")
    if os.path.exists(root_exe):
        os.remove(root_exe)
    # Sanity: the folder is self-contained and carries its own launcher.
    folder = os.path.join(DIST, NAME)
    assert os.path.isdir(folder), f"build folder missing: {folder}"
    launcher = os.path.join(folder, NAME + ".exe")
    assert os.path.exists(launcher), f"launcher missing in folder: {launcher}"
    assert not os.path.exists(root_exe), "redundant root exe was not removed"
    print(f"Build OK -> dist/{NAME}/  (root exe removed)")


if __name__ == "__main__":
    main()
