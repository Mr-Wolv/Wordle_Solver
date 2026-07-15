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

# The host machine may carry a global PYTHONPATH / system-wide .pth that injects
# an unrelated agent environment (boto3, openai, lxml, ...) into every Python
# process. If inherited, PyInstaller would freeze those extras into the bundle
# and the artifact would differ from the lean CI build (which installs only
# requirements.txt). Strip PYTHONPATH and disable user-site so only the project
# venv is the import source.
def _clean_env() -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    return env


ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "Wordle-Strat-Console"
SPEC = os.path.join(ROOT, "desktop_app.spec")
# Build into the repo-root dist/ (not nested under src/).
DIST = os.path.abspath(os.path.join(ROOT, "..", "..", "..", "dist"))


def main():
    if not os.path.exists(SPEC):
        sys.exit(f"spec not found: {SPEC}")
    # Build the one-folder bundle. Run with a sanitized environment so the
    # frozen artifact depends only on the project's pinned dependencies.
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC],
        check=True, env=_clean_env(),
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
