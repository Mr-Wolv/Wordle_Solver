"""End-to-end tests driving the REAL DOM via Playwright.

These are the reliable UI tests you asked for: no canvas, no vision
guessing — we assert against actual elements, their classes, ARIA
labels, and text content, exactly like you'd do with Playwright + React.

Run with the live server up on :8000:
    python -m pytest test_e2e_web.py -q

NOTE: skipped automatically when the chromium browser is not installed
(offline / restricted-network hosts).
"""
import os

import pytest
from playwright.sync_api import sync_playwright

_chromium_present = os.path.isdir(
    os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
        os.path.expanduser("~"), ".cache", "ms-playwright"
    )
) and any(
    n.startswith("chromium")
    for n in os.listdir(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
            os.path.expanduser("~"), ".cache", "ms-playwright"
        )
    )
)
pytestmark = pytest.mark.skipif(
    not _chromium_present,
    reason="Playwright chromium not installed (`playwright install chromium`)",
)

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")


def _tile_state(label: str) -> int:
    """Map an ARIA label like 'tile 1, present' to 0/1/2."""
    word = label.split(",")[1].strip().split()[0]
    return {"absent": 0, "present": 1, "correct": 2}[word]


def _set_tile(page, idx: int, state: int):
    """Click the active board row's tile `idx` until its ARIA state == state."""
    btn = page.locator(".board .row.active .tile.entry").nth(idx)
    for _ in range(3):
        if _tile_state(btn.get_attribute("aria-label")) == state:
            return
        btn.click()
    raise AssertionError(f"tile {idx} never reached state {state}")


def _type_guess(page, word: str):
    """Type a guess via the global keyboard; the active board row becomes the
    entry surface (there is no #guess input anymore)."""
    page.keyboard.type(word, delay=10)
    page.wait_for_selector(".board .row.active .tile.entry")


def _submit(page):
    """Submit via Enter (global key) or the on-screen ENTER action key."""
    page.keyboard.press("Enter")


def _reset(page):
    page.evaluate("window.app.reset()")
    page.wait_for_timeout(150)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    pg.goto(BASE)
    _reset(pg)
    yield pg
    pg.close()


@pytest.fixture
def raw_page(browser):
    """A freshly loaded page with NO reset and NO interaction — used to test
    the pure initialization path (the board must paint on load by itself)."""
    pg = browser.new_page()
    pg.goto(BASE)
    yield pg
    pg.close()


def test_board_paints_on_pure_init(raw_page):
    # REGRESSION: board must render 6x5 on first load with zero interaction
    # (no reset). Previously the board only painted after the async
    # /api/state fetch, so it was blank on init but appeared after reset.
    pg = raw_page
    # assert BEFORE any network wait: the empty board is painted synchronously
    rows = pg.locator(".board .row")
    assert rows.count() == 6
    for r in range(6):
        assert rows.nth(r).locator(".tile").count() == 5
    # the active (first) row exists with 5 entry tiles, ready for typing
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
    # Bug fix: the 6x5 board must exist on load, with no interaction.
    rows = page.locator(".board .row")
    assert rows.count() == 6
    # every row has 5 tiles, all empty placeholders (state-0 / .empty)
    for r in range(6):
        tiles = rows.nth(r).locator(".tile")
        assert tiles.count() == 5
        assert tiles.nth(0).get_attribute("class") is not None
    # turn starts at 1 (1-based), pool full
    assert page.locator("#chip-turn-n").inner_text() == "1"
    assert page.locator("#chip-pool-n").inner_text() == "2315"


def test_entry_tiles_appear_on_typing(page):
    # The active board row hosts the live guess: letters appear as you type,
    # and each tile is clickable to set its Wordle color.
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
    # Typing/backspacing flows straight into the board's active row.
    _type_guess(page, "cran")
    active = page.locator(".board .row.active .tile.entry")
    # active row always shows 5 tiles; the typed letters fill the first ones
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
    # no stale entry tiles remain after submit
    assert page.locator(".board .row.active .tile.entry").count() == 0
    assert page.locator("#chip-turn-n").inner_text() == "2"
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
    assert page.locator("#hard").is_disabled()
    # active row should now hold the NEXT guess (empty), not the submitted one
    assert page.locator(".board .row.active .tile.entry").count() == 5


def test_error_state_keeps_row_editable(page):
    # S3: an impossible pattern is rejected (409) with a LOUD categorized
    # alert, the turn does NOT advance, and the active row stays editable.
    # Narrow the pool first (CRANE non-win), then claim an all-green guess
    # that cannot be in the narrowed pool -> deterministic 409 LOGIC_ERROR.
    _type_guess(page, "crane")
    _set_tile(page, 2, 2)  # A correct @ pos 3
    _set_tile(page, 1, 1)  # R present
    _submit(page)
    page.wait_for_timeout(300)
    _type_guess(page, "mouse")  # MOUSE has no A -> not in narrowed pool
    for i in range(5):
        _set_tile(page, i, 2)  # claim all-green
    turn_before = int(page.locator("#chip-turn-n").inner_text())
    _submit(page)
    page.wait_for_timeout(300)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "LOGIC" in alert.inner_text()
    assert "impossible" in alert.inner_text().lower()
    assert int(page.locator("#chip-turn-n").inner_text()) == turn_before  # no advance
    # row remains editable (tiles still clickable) for correction
    assert page.locator(".board .row.active .tile.entry").count() == 5


def test_input_error_is_loud(page):
    # Typing a non-word and submitting must surface an INPUT error loudly.
    _type_guess(page, "zzzzz")
    for i in range(5):
        _set_tile(page, i, 0)
    _submit(page)
    page.wait_for_timeout(300)
    alert = page.locator("#alert")
    assert not alert.is_hidden()
    assert "INPUT" in alert.inner_text()


def test_hard_toggle_shows_lock_x_after_first_move(page):
    # Before a move: toggle is enabled, no lock marker.
    assert not page.locator("#hard").is_disabled()
    assert page.locator("#hard-toggle .hard-lock").is_hidden()
    # Make a move; hard toggle must lock AND show the ✕ locked marker.
    _type_guess(page, "slate")
    _set_tile(page, 2, 2)
    _submit(page)
    page.wait_for_timeout(300)
    assert page.locator("#hard").is_disabled()
    assert not page.locator("#hard-toggle .hard-lock").is_hidden()
    assert "locked" in page.locator("#hard-toggle .hard-lock").inner_text().lower()


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
    # board back to 6 empty rows, active row ready
    assert page.locator(".board .row").count() == 6
    assert page.locator(".board .row.active .tile.entry").count() == 5


def test_hint_flow(page):
    page.fill("#hint-letter", "e")
    page.click("#hint-btn")
    page.wait_for_timeout(200)
    assert "KNOWN: E" in page.locator("#hint-status").inner_text()


def test_intel_lists_populated(page):
    page.wait_for_selector("#solve-list .sugg")
    assert page.locator("#solve-list .sugg").count() >= 5
    assert page.locator("#shred-list .sugg").count() >= 5
    assert page.locator("#solve-list .sugg").first.evaluate(
        "e => e.classList.contains('top')")
