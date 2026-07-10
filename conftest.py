"""Shared pytest config.

The Playwright e2e suite is skipped at collection time when the chromium
browser is not installed (see the skipif marker at the top of
test_e2e_web.py). This keeps `pytest` green on hosts where the browser
binary can't be downloaded (e.g. restricted networks) without hiding
failures when the browser IS present.
"""
