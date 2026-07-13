"""Unit tests for the web backend (web_server.py).

Uses FastAPI's TestClient so no network/port is needed. Exercises the real
game logic end-to-end through the JSON API.

UI/flow contract (per the locked-six-domains design):
  * Domain DEFAULTS to normal 0 hints; no explicit start is required.
  * The Normal/Hard toggle (/api/hard) live-switches the domain
    (normal_0 <-> hard_0) before turn 1.
  * Logging hints (/api/hint) live-switches the 0-hint domain to 1/2 hints
    (normal_0 -> normal_1 -> normal_2, same for hard).
  * Everything locks after the first guess (mode_locked=True); further
    toggle/hint/start are refused (409).
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from wordle_solver.app import web_server

client = TestClient(web_server.app)


@pytest.fixture(autouse=True)
def _reset_before_each():
    # The web module keeps game state in a module-level global; reset it so
    # each test starts from a clean normal_0 domain (no cross-test leakage).
    client.post("/api/reset")


def _pattern(colors):
    return sum(c * (3 ** i) for i, c in enumerate(colors))


def _reset():
    return client.post("/api/reset").json()


def test_initial_state_defaults_normal_0():
    _reset()
    r = client.get("/api/state").json()
    assert r["started"] is False
    assert r["mode"] == "normal_0"
    assert r["hard"] is False
    assert r["mode_locked"] is False
    assert r["pool"] == 2315
    assert len(r["strat"]) >= 5  # board is alive on load


def test_default_is_normal_0_until_hard_toggled():
    _reset()
    assert client.get("/api/state").json()["mode"] == "normal_0"
    r = client.post("/api/hard", json={"on": True}).json()
    assert r["mode"] == "hard_0"
    assert r["hard"] is True
    # toggling back switches to normal_0 in real time (no hint wipe)
    r = client.post("/api/hard", json={"on": False}).json()
    assert r["mode"] == "normal_0"


def test_win_path_default_mode():
    r = client.post("/api/submit",
                    json={"guess": "crane", "colors": [2, 2, 2, 2, 2]}).json()
    assert r["solved"] is True
    assert r["turn"] == 1  # winning turn
    assert r["pool"] == 1
    assert r["mode"] == "normal_0"


def test_nonwin_narrows_pool_and_locks():
    _reset()
    colors = [0, 1, 2, 0, 0]
    r = client.post("/api/submit",
                    json={"guess": "slate", "colors": colors}).json()
    assert r["solved"] is False
    assert r["turn"] == 2
    assert 0 < r["pool"] < 2315
    # mode is now locked: a second hard toggle is refused
    r2 = client.post("/api/hard", json={"on": True})
    assert r2.status_code == 409


def test_impossible_pattern_rejected():
    _reset()
    r2 = client.post("/api/submit",
                     json={"guess": "zzzzz", "colors": [2, 2, 2, 2, 2]})
    assert r2.status_code == 400  # not a real word


def test_hint_rules_derive_2_hint_domain():
    # default normal_0 -> 1 hint -> normal_1 -> 2 hints -> normal_2
    _reset()
    s = client.get("/api/state").json()
    assert s["mode"] == "normal_0"
    client.post("/api/hint", json={"letter": "e"})
    s = client.get("/api/state").json()
    assert s["mode"] == "normal_1"
    client.post("/api/hint", json={"letter": "r"})
    s = client.get("/api/state").json()
    assert s["mode"] == "normal_2"
    assert set(s["hinted"]) == {"e", "r"}
    # third hint rejected (budget spent -> FULL / LOGIC)
    r3 = client.post("/api/hint", json={"letter": "t"})
    assert r3.status_code == 409
    # duplicate letter rejected as an INPUT error
    _reset()
    client.post("/api/hint", json={"letter": "e"})
    r4 = client.post("/api/hint", json={"letter": "e"})
    assert r4.status_code == 400
    assert r4.json()["detail"]["kind"] == "INPUT_ERROR"


def test_hints_locked_after_first_move():
    _reset()
    client.post("/api/hint", json={"letter": "e"})
    # submit a guess consistent with the 'e' hint (e is green at the end)
    client.post("/api/submit", json={"guess": "slate", "colors": [0, 1, 2, 0, 2]})
    r = client.post("/api/hint", json={"letter": "r"})
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "LOGIC_ERROR"


def test_hard_plus_hint_derives_hard_domain():
    _reset()
    client.post("/api/hard", json={"on": True})
    assert client.get("/api/state").json()["mode"] == "hard_0"
    client.post("/api/hint", json={"letter": "a"})
    assert client.get("/api/state").json()["mode"] == "hard_1"
    client.post("/api/hint", json={"letter": "b"})
    assert client.get("/api/state").json()["mode"] == "hard_2"


def test_errors_are_categorized():
    _reset()
    r = client.post("/api/submit", json={"guess": "abc", "colors": [0, 0, 0, 0, 0]})
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["kind"] == "INPUT_ERROR" and d["title"] and d["message"]
    r = client.post("/api/submit", json={"guess": "zzzzz", "colors": [0, 0, 0, 0, 0]})
    assert r.json()["detail"]["kind"] == "INPUT_ERROR"
    # LOGIC: mode lock — a hard toggle after a move is refused
    client.post("/api/submit", json={"guess": "slate", "colors": [0, 1, 2, 0, 0]})
    r = client.post("/api/hard", json={"on": True})
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "LOGIC_ERROR"


def test_state_exposes_ui_signals():
    _reset()
    s = client.get("/api/state").json()
    assert s["mode_locked"] is False
    assert s["specialist"] is False
    assert s["hint_remaining"] == "1 consonant + 1 vowel"
    client.post("/api/submit", json={"guess": "slate", "colors": [0, 1, 2, 0, 0]})
    st = client.get("/api/state").json()
    assert st["mode_locked"] is True
    assert st["mode"] == "normal_0"


def test_reset_clears_everything():
    client.post("/api/submit", json={"guess": "crane", "colors": [0, 1, 2, 0, 0]})
    client.post("/api/hint", json={"letter": "e"})
    r = _reset()
    assert r["turn"] == 1
    assert r["pool"] == 2315
    assert r["started"] is False
    assert r["mode"] == "normal_0"
    assert r["hinted"] == []


def test_pattern_int_encoding():
    assert _pattern([2, 2, 2, 2, 2]) == 2 + 2 * 3 + 2 * 9 + 2 * 27 + 2 * 81
    assert _pattern([0, 1, 2, 0, 0]) == 1 * 3 + 2 * 9
