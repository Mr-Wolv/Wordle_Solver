"""Workflow V&V — the user-facing flows, happy + unhappy.

Mirror of the backend flow at the UI boundary: every actionable workflow a
human can perform, asserted against the real DOM (Playwright). The UI shows
a Normal/Hard toggle + hint entry; the backend ESTABLISHES the domain (one
of six) from (hard, hint count) and locks it after the first guess.

Workflows covered:
  W1  Initialize game
  W2  Enter a guess
  W3  Color the feedback
  W4  Submit a losing guess
  W5  Submit a winning guess
  W6  Detect impossible fb
  W7  Mode lock after first move (toggle + hints disabled)
  W8  Hard toggle derives domain
  W9  Hint happy path (1 vowel + 1 consonant) -> normal_2
  W10 Hint rule violations (dup, 2nd vowel, 2nd cons, non-letter)
  W11 System reset
  W12 Game over boundary (6 rows used -> submit blocked)
  W13 Solved boundary (further submit blocked)
  W14 Forced-optimal note (hard + 2 hints)
  W15 Keyboard ergonomics (Enter logs hint)
"""

import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from _chromium import pytestmark

SECRET = {"crane": "crane", "slate": "slate", "mouse": "mouse"}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base_url():
    import wordle_solver.app.web_server as backend

    port = _free_port()
    backend.configure_engine(port)
    server = uvicorn.Server(
        uvicorn.Config(backend.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            if not thread.is_alive():
                raise RuntimeError("web_server failed to start")
    return f"http://127.0.0.1:{port}"


def _hard(page, on: bool):
    # Live Normal/Hard toggle (the game auto-starts as normal_0 on load).
    page.evaluate(
        "async (on) => { const r = await fetch('/api/hard',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({on})}); return r.status; }", on)


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
    page.keyboard.type(word, delay=10)
    page.wait_for_selector(".board .row.active .tile.entry")
    for i, c in enumerate(colors):
        _set(page, i, c)


def _submit(page):
    page.keyboard.press("Enter")
    # Wait for the app to finish the async submit (busy clears in finally)
    # before any further action — otherwise the entry buffer can be locked
    # (busy) and the next guess's keystrokes are silently ignored.
    page.wait_for_function(
        "() => !window.app || window.app.busy === false", timeout=8000)


def _wait_alert_clear(page):
    try:
        page.locator("#alert").wait_for(state="hidden", timeout=4000)
    except Exception:
        pass


def _ready(page):
    # The board + chips are populated by JS after the async /api/state fetch.
    # Wait for the App to mark the document ready so chip reads aren't racing
    # the initial render.
    page.wait_for_function(
        "() => document.documentElement.dataset.appReady === '1'", timeout=8000)


def _turn(page):
    _ready(page)
    return int(page.locator("#chip-turn-n").inner_text())


def _pool(page):
    _ready(page)
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
    # defaults to normal_0 on load; nothing to start explicitly
    # Wait for the App to finish its initial /api/state render so chip reads
    # aren't racing the async fetch.
    pg.wait_for_function(
        "() => document.documentElement.dataset.appReady === '1'", timeout=8000)
    yield pg
    pg.close()


def _reset(page):
    # Clears the shared backend game state (module-level global on the
    # module-scoped server) AND re-renders the frontend so the Normal/Hard
    # toggle is re-enabled and the hint status is fresh. Clicking #reset runs
    # the frontend reset() which POSTs /api/reset and re-renders.
    page.click("#reset")
    page.wait_for_timeout(120)


@pytest.fixture(autouse=True)
def _reset_each(page):
    # Each test must start from a clean normal_0 domain with the switches
    # enabled. The web module keeps game state in a module-level global shared
    # by the whole module-scoped server, and the frontend App keeps its own
    # UI state, so reset both (this is what makes the "lock after turn 1"
    # tests stable).
    _reset(page)


# ── W1: initialize ─────────────────────────────────────────────
def test_W1_initialize(page):
    assert page.locator(".board .row").count() == 6
    assert page.locator(".board .row.active .tile.entry").count() == 5
    assert _turn(page) == 1
    assert _pool(page) == 2315
    assert page.locator("#chip-mode").inner_text() == "NORMAL"
    assert not page.locator("#hard").is_disabled()


# ── W2: enter a guess ──────────────────────────────────────────
def test_W2_enter_guess(page):
    page.keyboard.type("crane", delay=10)
    page.wait_for_selector(".board .row.active .tile.entry")
    active = page.locator(".board .row.active .tile.entry")
    assert active.nth(0).inner_text() == "C" and active.nth(4).inner_text() == "E"
    page.keyboard.press("Backspace")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(80)
    active = page.locator(".board .row.active .tile.entry")
    assert active.nth(0).inner_text() == "C"
    assert active.nth(2).inner_text() == "A"


# ── W3: color the feedback ─────────────────────────────────────
def test_W3_color_feedback(page):
    page.keyboard.type("crane", delay=10)
    page.wait_for_selector(".board .row.active .tile.entry")
    t = page.locator(".board .row.active .tile.entry").nth(0)
    t.click()
    assert "present" in t.get_attribute("aria-label")
    t.click()
    assert "correct" in t.get_attribute("aria-label")
    t.click()
    assert "absent" in t.get_attribute("aria-label")


# ── W4: submit a losing guess (happy) ──────────────────────────
def test_W4_submit_losing(page):
    before = _pool(page)
    _set_word(page, "slate", [0, 1, 2, 0, 0])
    _submit(page)
    page.wait_for_timeout(250)
    assert _turn(page) == 2
    assert 0 < _pool(page) < before
    row0 = page.locator(".board .row").nth(0)
    assert row0.inner_text().replace("\n", "").startswith("SLATE")
    assert page.locator(".board .row.active .tile.entry").count() == 5


# ── W5: submit a winning guess (happy) ─────────────────────────
def test_W5_submit_winning(page):
    _set_word(page, "crane", [2, 2, 2, 2, 2])
    _submit(page)
    page.wait_for_timeout(250)
    assert not page.locator("#banner").is_hidden()
    assert page.locator("#chip-pool-n").inner_text() == "1"
    assert page.locator(".board .row.active .tile.entry").count() == 0
    assert "SUCCESS" in page.locator("#alert").inner_text()


# ── W6: impossible feedback (unhappy) ──────────────────────────
def test_W6_impossible_feedback(page):
    _set_word(page, "crane", [0, 1, 2, 0, 0])
    _submit(page)
    page.wait_for_timeout(250)
    _set_word(page, "mouse", [2, 2, 2, 2, 2])
    turn_before = _turn(page)
    _submit(page)
    page.wait_for_timeout(250)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "LOGIC" in alert.inner_text()
    assert "impossible" in alert.inner_text().lower()
    assert _turn(page) == turn_before
    assert page.locator(".board .row.active .tile.entry").count() == 5


# ── W7: mode lock after first move (toggle + hints disabled) ────
def test_W7_mode_locked_after_first_move(page):
    assert not page.locator("#hard").is_disabled()
    _set_word(page, "slate", [0, 1, 2, 0, 0])
    _submit(page)
    page.wait_for_timeout(250)
    assert page.locator("#hard").is_disabled()
    assert page.locator("#hint-letter").is_disabled()
    resp = page.evaluate(
        "async () => { const r = await fetch('/api/hard',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({on:true})}); return r.status; }")
    assert resp == 409


# ── W8: hard toggle derives domain ─────────────────────────────
def test_W8_hard_toggle_derives_domain(page):
    page.click("#hard")
    # Wait for the live toggle to derive the hard_0 domain (backend POST +
    # re-render), rather than a fixed sleep that races a busy server.
    page.wait_for_function(
        "() => document.getElementById('chip-mode').innerText === 'HARD'",
        timeout=8000)
    assert page.locator("#chip-mode").inner_text() == "HARD"
    state = page.evaluate("async () => (await fetch('/api/state')).json()")
    assert state["mode"] == "hard_0"


# ── W9: hint happy path (1 vowel + 1 consonant) -> normal_2 ────
def test_W9_hint_happy(page):
    page.fill("#hint-letter", "e")
    page.click("#hint-btn")
    # Wait for the live hint to derive normal_1 (backend POST + re-render).
    page.wait_for_function(
        "() => /KNOWN: E/.test(document.getElementById('hint-status').innerText)"
        " && /need 1 consonant/.test(document.getElementById('hint-status').innerText)",
        timeout=8000)
    before = _pool(page)
    page.fill("#hint-letter", "r")
    page.click("#hint-btn")
    # Wait for the second hint to derive normal_2 (budget full -> 'complete').
    page.wait_for_function(
        "() => /complete/.test(document.getElementById('hint-status').innerText)",
        timeout=8000)
    assert _pool(page) < before
    mode = page.evaluate("async () => (await fetch('/api/state')).json()")["mode"]
    assert mode == "normal_2"


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
    assert "INPUT" in page.locator("#alert").inner_text()
    # second vowel rejected (LOGIC)
    page.fill("#hint-letter", "a")
    page.click("#hint-btn")
    page.wait_for_timeout(120)
    assert "LOGIC" in page.locator("#alert").inner_text()


# ── W11: system reset (happy) ──────────────────────────────────
def test_W11_system_reset(page):
    _set_word(page, "crane", [2, 2, 2, 2, 2])
    _submit(page)
    page.wait_for_timeout(200)
    page.click("#reset")
    page.wait_for_timeout(250)
    assert _turn(page) == 1
    assert _pool(page) == 2315
    assert page.locator("#banner").is_hidden()
    assert page.locator(".board .row").count() == 6
    assert page.locator(".board .row.active .tile.entry").count() == 5
    assert page.locator("#hint-status").inner_text() == "OPTIONAL hint: reveal 1 consonant + 1 vowel"


# ── W12: game over boundary (6 rows used) (unhappy) ────────────
def test_W12_game_over_boundary(page):
    secret = "robot"
    for _ in range(6):
        if not page.locator(".board .row.active .tile.entry").count():
            break
        if not page.locator("#banner").is_hidden():
            break
        top = page.locator("#solve-list .sugg .word").first.inner_text()
        colors = []
        out = [0] * 5
        s: list[str | None] = list(secret)
        g = list(top.lower())
        for i in range(5):
            if g[i] == s[i]:
                out[i] = 2
                s[i] = None
        for i in range(5):
            if out[i] == 0 and g[i] in s:
                out[i] = 1
                s[s.index(g[i])] = None
        _set_word(page, top, out)
        _submit(page)
        page.wait_for_timeout(180)
    board_full = page.locator(".board .row.active .tile.entry").count() == 0
    solved = not page.locator("#banner").is_hidden()
    assert board_full or solved
    _wait_alert_clear(page)
    page.keyboard.type("about", delay=10)
    page.wait_for_timeout(80)
    _submit(page)
    page.wait_for_timeout(180)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "No guesses left" in alert.inner_text() or "Already solved" in alert.inner_text()


# ── W13: solved boundary (further submit blocked) (unhappy) ────
def test_W13_solved_boundary(page):
    _set_word(page, "crane", [2, 2, 2, 2, 2])
    _submit(page)
    page.wait_for_timeout(200)
    _wait_alert_clear(page)
    page.keyboard.type("about", delay=10)
    page.wait_for_timeout(60)
    _submit(page)
    page.wait_for_timeout(180)
    assert "Already solved" in page.locator("#alert").inner_text()


# ── W14: forced-optimal note when hard + 2 hints ────────────────
def test_W14_forced_optimal_note(page):
    page.click("#hard")
    page.wait_for_timeout(120)
    page.fill("#hint-letter", "h")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    page.fill("#hint-letter", "a")
    page.click("#hint-btn")
    page.wait_for_timeout(150)
    note = page.locator("#solve-note")
    assert (not note.is_hidden()) or _pool(page) == 1


# ── W15: keyboard ergonomics (Enter logs hint) (happy) ────────
def test_W15_hint_enter_key(page):
    page.fill("#hint-letter", "e")
    page.press("#hint-letter", "Enter")
    page.wait_for_timeout(150)
    assert "KNOWN: E" in page.locator("#hint-status").inner_text()
    assert page.locator("#hint-letter").input_value() == ""
