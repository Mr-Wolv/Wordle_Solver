"""Shared pytest config.

Both Playwright suites (test_e2e_web.py and test_workflows_web.py) are
skipped at collection time when the chromium browser is not installed
(see the skipif marker at the top of each file). This keeps `pytest` green
on hosts where the browser binary can't be downloaded (e.g. restricted
networks) without hiding failures when the browser IS present.

The exhaustive closed-loop regression gate (test_game_contract.py::
test_exhaustive_contract) is marked `exhaustive` and excluded from the
default run via pytest.ini (addopts = -m "not exhaustive"); run it with
`pytest -m exhaustive`.

We inject ``src/`` onto ``sys.path`` (rootdir-relative) so the
``wordle_solver`` package imports in tests without requiring a ``pip install
-e`` of the project. This keeps the layout editable in dev and identical under
the frozen bundle (where the package is instead found on ``sys._MEIPASS``).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")

# Neutralise a host environment that leaks an unrelated agent virtualenv onto
# sys.path (e.g. the Hermes runtime prepends its own venv). If left in place it
# shadows the project's .venv for packages like pydantic/pydantic_core, causing
# ABI-mismatch import errors. Removing those foreign site-packages paths lets the
# project's own .venv win. Harmless on clean CI (no such path present).
_PROJECT_VENV = os.path.join(_ROOT, ".venv", "Lib", "site-packages")
for _p in list(sys.path):
    _lp = _p.lower().replace("\\", "/")
    if "hermes" in _lp and "site-packages" in _lp and _lp != _PROJECT_VENV.lower().replace("\\", "/"):
        try:
            sys.path.remove(_p)
        except ValueError:
            pass

if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
