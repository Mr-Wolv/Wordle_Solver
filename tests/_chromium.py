"""Shared chromium-availability guard for the browser-driven web tests.

Both ``test_e2e_web.py`` and ``test_workflows_web.py`` import ``pytestmark``
from here so the whole module is skipped when a usable Chromium browser is
not installed (keeps CI green on machines without a browser). The guard is
defensive: it probes for Playwright's Chromium and falls back to a skip if
the import or the browser build is missing.
"""

from __future__ import annotations

import shutil

import pytest

_CHROMIUM_BIN = shutil.which("chromium") or shutil.which("chromium-browser")


def _chromium_available() -> bool:
    if _CHROMIUM_BIN:
        return True
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # resolve the executable path; raises if the browser build is absent
            return p.chromium.executable_path is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="Chromium (Playwright) not available",
)
