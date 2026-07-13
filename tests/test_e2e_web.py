"""End-to-end tests driving the REAL DOM via Playwright.

These assert against actual elements, classes, ARIA labels, and text
content (no canvas, no vision guessing). The suite stands up its own
FastAPI backend on an ephemeral port.

UI flow: the page exposes a Normal/Hard toggle (id #hard) + hint entry
(#hint-letter / #hint-btn). The backend ESTABLISHES the domain (one of
six) from (hard, hint count) and locks it after the first guess — so the
toggle + hint input are disabled from turn 2 on.
"""

import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from _chromium import pytestmark  # shared chromium-availability guard


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


def _tile_state(label: str) -> int:
    word = label.split(",")[1].strip().split()[0]
    return {"absent": 0, "present": 1, "correct": 2}[word]


def _set_tile(page, idx: int, state: int):
    btn = page.locator(".board .row.active .tile.entry").nth(idx)
    for _ in range(3):
        if _tile_state(btn.get_attribute("aria-label")) == state:
            return
        btn.click()
    raise AssertionError(f"tile {idx} never reached state {state}")


def _type_guess(page, word: str):
    page.keyboard.type(word, delay=10)
    page.wait_for_selector(".board .row.active .tile.entry")


def _submit(page):
    page.keyboard.press("Enter")
    # Wait for the app to finish the async submit (busy clears in finally)
    # before any further action — otherwise the entry buffer can be locked
    # (busy) and the next guess's keystrokes are silently ignored.
    page.wait_for_function(
        "() => !window.app || window.app.busy === false", timeout=8000)


def _hard(page, on: bool):
    # Live Normal/Hard toggle (the game auto-starts as normal_0 on load).
    page.evaluate(
        "async (on) => { const r = await fetch('/api/hard',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({on})}); return r.status; }", on)


def _reset(page):
    page.click("#reset")
    page.wait_for_timeout(120)


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
    # Wait for the App to finish its initial /api/state render so chip reads
    # aren't racing the async fetch.
    pg.wait_for_function(
        "() => document.documentElement.dataset.appReady === '1'", timeout=8000)
    yield pg
    pg.close()


@pytest.fixture(autouse=True)
def _reset_each(page):
    # The web module keeps game state in a module-level global shared by the
    # whole module-scoped server, AND the frontend App holds its own entry
    # buffer / busy flag. Reset both so a prior test's state can't leak into
    # the next one (this is what makes the "lock after turn 1" tests stable).
    _reset(page)
    page.evaluate(
        "() => { if (window.app) { window.app.typed=''; window.app.busy=false;"
        " window.app.solved=false; window.app.entryColors=[0,0,0,0,0]; } }")


@pytest.fixture
def raw_page(browser, base_url):
    pg = browser.new_page()
    pg.goto(base_url)
    yield pg
    pg.close()


def test_board_paints_on_pure_init(raw_page):
    pg = raw_page
    rows = pg.locator(".board .row")
    assert rows.count() == 6
    for r in range(6):
        assert rows.nth(r).locator(".tile").count() == 5
    assert pg.locator(".board .row.active .tile.entry").count() == 5


def test_layout_is_real_dom(page):
    assert page.locator("#card-board").count() == 1
    assert page.locator("#card-command").count() == 1
    assert page.locator("#card-intel").count() == 1
    assert page.get_by_role("heading", name="GAME BOARD").count() == 1
    assert page.locator("#keyboard").count() == 1
    assert page.locator("#keyboard .key-action", has_text="ENTER").count() == 1
    assert page.locator("#keyboard .key-action", has_text="DELETE").count() == 1
    box = page.locator(".board").bounding_box()
    assert box is not None and box["width"] > 0


def test_board_renders_on_initial_load(page):
    rows = page.locator(".board .row")
    assert rows.count() == 6
    for r in range(6):
        tiles = rows.nth(r).locator(".tile")
        assert tiles.count() == 5
        assert tiles.nth(0).get_attribute("class") is not None
    assert page.locator("#chip-turn-n").inner_text() == "1"
    assert page.locator("#chip-pool-n").inner_text() == "2315"


def test_entry_tiles_appear_on_typing(page):
    _type_guess(page, "crane")
    tiles = page.locator(".board .row.active .tile.entry")
    assert tiles.count() == 5
    assert tiles.nth(0).inner_text() == "C"
    assert tiles.nth(4).inner_text() == "E"


def test_tile_color_cycles(page):
    _type_guess(page, "crane")
    t = page.locator(".board .row.active .tile.entry").nth(0)
    assert "absent" in t.get_attribute("aria-label")
    t.click()
    assert "present" in t.get_attribute("aria-label")
    t.click()
    assert "correct" in t.get_attribute("aria-label")
    t.click()
    assert "absent" in t.get_attribute("aria-label")


def test_letter_syncs_to_board_on_type(page):
    _type_guess(page, "cran")
    active = page.locator(".board .row.active .tile.entry")
    assert active.count() == 5
    assert active.nth(0).inner_text() == "C"
    assert active.nth(2).inner_text() == "A"
    assert active.nth(3).inner_text() == "N"
    page.keyboard.type("e", delay=10)
    page.wait_for_timeout(150)
    active = page.locator(".board .row.active .tile.entry")
    assert active.nth(0).inner_text() == "C"
    assert active.nth(4).inner_text() == "E"


def test_win_flow_updates_board_and_chip(page):
    _type_guess(page, "crane")
    for i in range(5):
        _set_tile(page, i, 2)
    _submit(page)
    page.wait_for_timeout(300)
    row0 = page.locator(".board .row").nth(0)
    assert row0.inner_text().replace("\n", "").startswith("CRANE")
    assert row0.locator(".tile.state-2").count() == 5
    assert page.locator(".board .row.active .tile.entry").count() == 0
    assert page.locator("#chip-turn-n").inner_text() == "1"
    assert page.locator("#chip-pool-n").inner_text() == "1"
    assert not page.locator("#banner").is_hidden()


def test_nonwin_narrows_pool(page):
    _type_guess(page, "slate")
    _set_tile(page, 1, 1)
    _set_tile(page, 2, 2)
    _submit(page)
    page.wait_for_timeout(300)
    pool = int(page.locator("#chip-pool-n").inner_text())
    assert 0 < pool < 2315
    # toggle is locked after the first move
    assert page.locator("#hard").is_disabled()
    assert page.locator(".board .row.active .tile.entry").count() == 5


def test_error_state_keeps_row_editable(page):
    _type_guess(page, "crane")
    _set_tile(page, 2, 2)
    _set_tile(page, 1, 1)
    _submit(page)
    page.wait_for_timeout(300)
    _type_guess(page, "mouse")
    for i in range(5):
        _set_tile(page, i, 2)
    turn_before = int(page.locator("#chip-turn-n").inner_text())
    _submit(page)
    page.wait_for_timeout(300)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "LOGIC" in alert.inner_text()
    assert "impossible" in alert.inner_text().lower()
    assert int(page.locator("#chip-turn-n").inner_text()) == turn_before
    assert page.locator(".board .row.active .tile.entry").count() == 5


def test_input_error_is_loud(page):
    _type_guess(page, "zzzzz")
    for i in range(5):
        _set_tile(page, i, 0)
    _submit(page)
    page.wait_for_timeout(300)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "INPUT" in alert.inner_text()


def test_mode_locked_after_first_move(page):
    # Before a move: the toggle is enabled.
    assert not page.locator("#hard").is_disabled()
    _type_guess(page, "slate")
    _set_tile(page, 2, 2)
    _submit(page)
    page.wait_for_timeout(300)
    # After the first move the toggle + hint input are locked.
    assert page.locator("#hard").is_disabled()
    assert page.locator("#hint-letter").is_disabled()
    resp = page.evaluate(
        "async () => { const r = await fetch('/api/hard',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({on:true})}); return r.status; }")
    assert resp == 409


def test_reset_clears(page):
    _type_guess(page, "crane")
    for i in range(5):
        _set_tile(page, i, 2)
    _submit(page)
    page.wait_for_timeout(200)
    page.click("#reset")
    page.wait_for_timeout(300)
    assert page.locator("#chip-turn-n").inner_text() == "1"
    assert page.locator("#chip-pool-n").inner_text() == "2315"
    assert page.locator("#banner").is_hidden()
    assert page.locator(".board .row").count() == 6
    # after reset, toggle is re-enabled
    assert page.locator("#hard").is_disabled() is False


def test_hint_flow(page):
    _reset(page)
    page.fill("#hint-letter", "e")
    page.click("#hint-btn")
    page.wait_for_timeout(200)
    assert "KNOWN: E" in page.locator("#hint-status").inner_text()


def test_calculating_overlay_clears_after_move(page):
    # The STRATEGY card shows a "calculating" overlay during the heavy
    # exact-minimax solve so a multi-second think reads as working, not
    # frozen. After the move resolves the overlay must clear (never stuck).
    assert page.locator("#calc-overlay").count() == 1
    # Initially idle -> no calculating state.
    assert not page.locator("#card-intel").evaluate(
        "e => e.classList.contains('calculating')")
    _type_guess(page, "slate")
    _set_tile(page, 2, 2)
    _submit(page)
    page.wait_for_timeout(300)
    # Overlay must have cleared after the move settled (busy false in finally).
    assert not page.locator("#card-intel").evaluate(
        "e => e.classList.contains('calculating')")


def test_intel_lists_populated(page):
    page.wait_for_selector("#solve-list .sugg")
    assert page.locator("#solve-list .sugg").count() >= 5
    assert page.locator("#shred-list .sugg").count() >= 5
    assert page.locator("#solve-list .sugg").first.evaluate(
        "e => e.classList.contains('top')")
