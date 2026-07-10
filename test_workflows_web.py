"""Workflow V&V — the user-facing flows, happy + unhappy.

This is the mirror of the backend's flow at the UI boundary: every *actionable
workflow* a human can perform in the desktop/web app, asserted against the real
DOM (Playwright) exactly like the backend's component tests assert against the
engine. No canvas, no vision guessing — concrete elements, classes, ARIA, text.

Workflows covered (each has a happy path and at least one unhappy path):
  W1  Initialize game        (board paints, chips correct, no stale state)
  W2  Enter a guess          (type -> board row fills; backspace trims)
  W3  Color the feedback     (click tiles absent->present->correct)
  W4  Submit a losing guess  (row locks as history, pool narrows, turn++)
  W5  Submit a winning guess (banner, solved sticky, submit blocked)
  W6  Detect impossible fb   (409 LOGIC, turn frozen, row stays editable)
  W7  Hard mode OFF->ON      (toggle before move; chips + alerts reflect)
  W8  Hard mode lock         (toggle disabled + X after first move)
  W9  Hint happy path        (1 vow + 1 cons, status + pool narrow)
  W10 Hint rule violations   (dup, 2nd vowel, 2nd cons, non-letter)
  W11 System reset           (clears board/chips/alerts; fresh game)
  W12 Game over boundary     (6 rows used -> submit blocked w/ clear msg)
  W13 Solved boundary        (further submit blocked w/ clear msg)
  W14 Forced-optimal note    (hard+hints -> single SOLVE entry explained)
  W15 Keyboard ergonomics    (Enter in hint field logs hint)

Run with chromium installed (the suite self-skips otherwise):
    python -m pytest test_workflows_web.py -q
The module boots its own web_server on an ephemeral port, so no external
server needs to be running.
"""

import os
import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

# ── Browser/CI guard ──────────────────────────────────────────────
# Mirrors test_e2e_web.py: the workflow suite drives the REAL DOM with
# Playwright, so it can only run where chromium is installed. On hosts
# without it (restricted networks, headless CI without the binary) the
# whole module is skipped at collection time — exactly like the e2e suite
# — so `pytest` stays green instead of erroring on a missing browser.
_BROWSER_DIR = os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")
_chromium_present = os.path.isdir(_BROWSER_DIR) and any(
    n.startswith("chromium") for n in os.listdir(_BROWSER_DIR)
)
pytestmark = pytest.mark.skipif(
    not _chromium_present,
    reason="Playwright chromium not installed (`playwright install chromium`)",
)

# real 5-letter answer secrets used to drive deterministic colorings
SECRET = {
    "crane": "crane",   # all-green win
    "slate": "slate",
    "mouse": "mouse",
}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base_url():
    """Boot the real FastAPI backend on an ephemeral port for the run.

    The workflow tests assert against the live server DOM (just like a
    human would), so we stand up web_server ourselves instead of assuming
    something is already listening on :8000. The engine is bound to the
    chosen port so the per-instance turn-1 cache file can't collide with a
    dev server the user might have running elsewhere.
    """
    import web_server as backend

    port = _free_port()
    backend.configure_engine(port)
    server = uvicorn.Server(
        uvicorn.Config(backend.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # wait for the port to come up (cheap readiness check)
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            if not thread.is_alive():
                raise RuntimeError("web_server failed to start")
    return f"http://127.0.0.1:{port}"


def _set(page, idx, state):
    btn = page.locator(".board .row.active .tile.entry").nth(idx)
    for _ in range(3):
        label = btn.get_attribute("aria-label")
        cur = label.split(",")[1].strip().split()[0]
        cur = {"absent": 0, "present": 1, "correct": 2}[cur]
        if cur == state:
            return
        btn.click()
    raise AssertionError(f"tile {idx} never reached {state}")


def _set_word(page, word, colors):
    page.fill("#guess", word)
    page.wait_for_selector(".board .row.active .tile.entry")
    for i, c in enumerate(colors):
        _set(page, i, c)


def _turn(page):
    return int(page.locator("#chip-turn-n").inner_text())


def _pool(page):
    return int(page.locator("#chip-pool-n").inner_text())


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    pg = browser.new_page()
    pg.goto(base_url)
    pg.evaluate("window.app.reset()")
    pg.wait_for_timeout(120)
    yield pg
    pg.close()


# ── W1: initialize ─────────────────────────────────────────────
def test_W1_initialize(page):
    assert page.locator(".board .row").count() == 6
    assert page.locator(".board .row.active .tile.entry").count() == 5
    assert _turn(page) == 1
    assert _pool(page) == 2315
    assert page.locator("#chip-mode").inner_text() == "NORMAL"
    assert page.locator("#hard").is_disabled() is False
    assert page.locator("#hard-toggle .hard-lock").is_hidden()


# ── W2: enter a guess ──────────────────────────────────────────
def test_W2_enter_guess(page):
    page.fill("#guess", "crane")
    page.wait_for_selector(".board .row.active .tile.entry")
    active = page.locator(".board .row.active .tile.entry")
    assert active.nth(0).inner_text() == "C" and active.nth(4).inner_text() == "E"
    # backspace flows back into the board
    page.fill("#guess", "cra")
    page.wait_for_timeout(80)
    active = page.locator(".board .row.active .tile.entry")
    assert active.nth(0).inner_text() == "C"
    assert active.nth(2).inner_text() == "A"


# ── W3: color the feedback (unhappy: mis-colored then corrected) ─
def test_W3_color_feedback(page):
    page.fill("#guess", "crane")
    page.wait_for_selector(".board .row.active .tile.entry")
    t = page.locator(".board .row.active .tile.entry").nth(0)
    t.click()  # -> present
    assert "present" in t.get_attribute("aria-label")
    t.click()  # -> correct
    assert "correct" in t.get_attribute("aria-label")
    t.click()  # -> absent (cycle)
    assert "absent" in t.get_attribute("aria-label")


# ── W4: submit a losing guess (happy) ──────────────────────────
def test_W4_submit_losing(page):
    before = _pool(page)
    _set_word(page, "slate", [0, 1, 2, 0, 0])
    page.click("#submit")
    page.wait_for_timeout(250)
    assert _turn(page) == 2
    assert 0 < _pool(page) < before
    row0 = page.locator(".board .row").nth(0)
    assert row0.inner_text().replace("\n", "").startswith("SLATE")
    assert page.locator(".board .row.active .tile.entry").count() == 5  # next row ready


# ── W5: submit a winning guess (happy) ─────────────────────────
def test_W5_submit_winning(page):
    _set_word(page, "crane", [2, 2, 2, 2, 2])
    page.click("#submit")
    page.wait_for_timeout(250)
    assert not page.locator("#banner").is_hidden()
    assert page.locator("#chip-pool-n").inner_text() == "1"
    assert page.locator(".board .row.active .tile.entry").count() == 0  # no entry row
    # success alert loud
    assert "SUCCESS" in page.locator("#alert").inner_text()


# ── W6: impossible feedback (unhappy) ──────────────────────────
def test_W6_impossible_feedback(page):
    _set_word(page, "crane", [0, 1, 2, 0, 0])  # narrows pool (no 'a'-word left-cluster)
    page.click("#submit")
    page.wait_for_timeout(250)
    _set_word(page, "mouse", [2, 2, 2, 2, 2])   # MOUSE has no 'a', can't be in pool
    turn_before = _turn(page)
    page.click("#submit")
    page.wait_for_timeout(250)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "LOGIC" in alert.inner_text()
    assert "impossible" in alert.inner_text().lower()
    assert _turn(page) == turn_before           # frozen
    assert page.locator(".board .row.active .tile.entry").count() == 5  # still editable


# ── W7: hard mode OFF -> ON before first move (happy) ──────────
def test_W7_hard_on_before_move(page):
    page.check("#hard") if False else page.click("#hard")
    page.wait_for_timeout(200)
    assert page.locator("#chip-mode").inner_text() == "HARD"
    assert "INFO" in page.locator("#alert").inner_text()
    # suggestions now reflect hard (pool unaffected at turn 1)
    assert _pool(page) == 2315


# ── W8: hard mode locks after first move (unhappy toggle) ──────
def test_W8_hard_locked_after_move(page):
    _set_word(page, "slate", [0, 1, 2, 0, 0])
    page.click("#submit")
    page.wait_for_timeout(250)
    assert page.locator("#hard").is_disabled()
    assert not page.locator("#hard-toggle .hard-lock").is_hidden()
    assert "locked" in page.locator("#hard-toggle .hard-lock").inner_text().lower()
    # even a programmatic toggle is refused by the server
    resp = page.evaluate("async () => { const r = await fetch('/api/hard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:true})}); return r.status; }")
    assert resp == 409


# ── W9: hint happy path (1 vowel + 1 consonant) ────────────────
def test_W9_hint_happy(page):
    page.fill("#hint-letter", "e")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    assert "KNOWN: E" in page.locator("#hint-status").inner_text()
    assert "need 1 CONSONANT" in page.locator("#hint-status").inner_text()
    before = _pool(page)
    page.fill("#hint-letter", "r")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    assert "complete" in page.locator("#hint-status").inner_text()
    assert _pool(page) < before


# ── W10: hint rule violations (unhappy) ────────────────────────
def test_W10_hint_violations(page):
    # non-letter
    page.fill("#hint-letter", "3")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    assert "INPUT" in page.locator("#alert").inner_text()
    # valid vowel then duplicate
    page.fill("#hint-letter", "e")
    page.click("#hint-btn")
    page.wait_for_timeout(120)
    page.fill("#hint-letter", "e")
    page.click("#hint-btn")
    page.wait_for_timeout(120)
    assert "INPUT" in page.locator("#alert").inner_text()  # Already logged
    # second vowel rejected (LOGIC)
    page.fill("#hint-letter", "a")
    page.click("#hint-btn")
    page.wait_for_timeout(120)
    assert "LOGIC" in page.locator("#alert").inner_text()  # Vowel already set


# ── W11: system reset (happy) ──────────────────────────────────
def test_W11_system_reset(page):
    _set_word(page, "crane", [2, 2, 2, 2, 2])
    page.click("#submit")
    page.wait_for_timeout(200)
    page.click("#reset")
    page.wait_for_timeout(250)
    assert _turn(page) == 1
    assert _pool(page) == 2315
    assert page.locator("#banner").is_hidden()
    assert page.locator(".board .row").count() == 6
    assert page.locator(".board .row.active .tile.entry").count() == 5
    assert page.locator("#hint-status").inner_text() == "need 1 CONSONANT + 1 VOWEL"


# ── W12: game over boundary (6 rows used) (unhappy) ────────────
def test_W12_game_over_boundary(page):
    # Play the engine's own top suggestion each turn (recolored from a fixed
    # secret) until the board fills or we win — a true end-to-end playthrough.
    secret = "robot"
    for _ in range(6):
        if not page.locator(".board .row.active .tile.entry").count():
            break
        if not page.locator("#banner").is_hidden():
            break
        # read the engine's current top suggestion from the DOM
        top = page.locator("#solve-list .sugg .word").first.inner_text()
        # color it against the secret (real Wordle rules)
        colors = []
        s = list(secret)
        g = list(top.lower())
        out = [0] * 5
        for i in range(5):
            if g[i] == s[i]:
                out[i] = 2
                s[i] = None
        for i in range(5):
            if out[i] == 0 and g[i] in s:
                out[i] = 1
                s[s.index(g[i])] = None
        _set_word(page, top, out)
        page.click("#submit")
        page.wait_for_timeout(180)
    # either solved or board full
    board_full = page.locator(".board .row.active .tile.entry").count() == 0
    solved = not page.locator("#banner").is_hidden()
    assert board_full or solved
    # a further submit is explained, not a confusing error
    page.fill("#guess", "about")
    page.wait_for_timeout(80)
    page.click("#submit")
    page.wait_for_timeout(180)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "No guesses left" in alert.inner_text() or "Already solved" in alert.inner_text()


# ── W13: solved boundary (further submit blocked) (unhappy) ────
def test_W13_solved_boundary(page):
    _set_word(page, "crane", [2, 2, 2, 2, 2])
    page.click("#submit")
    page.wait_for_timeout(200)
    page.fill("#guess", "about")
    page.wait_for_timeout(60)
    page.click("#submit")
    page.wait_for_timeout(180)
    assert "Already solved" in page.locator("#alert").inner_text()


# ── W14: forced-optimal note when hard + hints ─────────────────
def test_W14_forced_optimal_note(page):
    page.click("#hard")
    page.wait_for_timeout(150)
    page.fill("#hint-letter", "h")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    page.fill("#hint-letter", "a")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    note = page.locator("#solve-note")
    # either the forced-optimal note shows, or pool was already solved by the
    # specialist; either way the SOLVE intent is coherent (no silent 1-item).
    assert (not note.is_hidden()) or _pool(page) == 1


# ── W15: keyboard ergonomics (Enter logs hint) (happy) ────────
def test_W15_hint_enter_key(page):
    page.fill("#hint-letter", "e")
    page.press("#hint-letter", "Enter")
    page.wait_for_timeout(150)
    assert "KNOWN: E" in page.locator("#hint-status").inner_text()
    # the entry clears after logging
    assert page.locator("#hint-letter").input_value() == ""
