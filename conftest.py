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
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
