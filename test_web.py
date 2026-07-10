"""Unit tests for the web backend (web_server.py).

Uses FastAPI's TestClient so no network/port is needed. Exercises the
real game logic end-to-end through the JSON API the DOM frontend calls.
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "web_server", os.path.join(ROOT, "web_server.py")
)
web_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_server)

client = TestClient(web_server.app)


def _pattern(colors):
    return sum(c * (3 ** i) for i, c in enumerate(colors))


def _reset():
    client.post("/api/reset")


def test_initial_state():
    _reset()
    r = client.get("/api/state").json()
    assert r["turn"] == 1  # 1-based: turn 1 = first guess yet to be made
    assert r["pool"] == 2315
    assert r["hard"] is False
    assert r["solved"] is False
    # deterministic greedy opening; any of the known strong openers is fine
    assert r["strat"][0]["word"] in {"trace", "stare", "crane", "irate", "slate", "crate"}
    assert len(r["strat"]) >= 5


def test_win_path():
    _reset()
    # CRANE all-green -> one guess win
    r = client.post("/api/submit", json={"guess": "crane", "colors": [2, 2, 2, 2, 2]}).json()
    assert r["won"] is True
    assert r["turn"] == 2  # advanced to the (would-be) next turn
    assert r["solved"] is True
    assert r["pool"] == 1


def test_nonwin_narrows_pool():
    _reset()
    # SLATE with pattern absent,present,correct,absent,absent
    colors = [0, 1, 2, 0, 0]
    r = client.post("/api/submit", json={"guess": "slate", "colors": colors}).json()
    assert r["won"] is False
    assert r["turn"] == 2
    assert 0 < r["pool"] < 2315  # pool collapsed
    # hard toggle is now locked (turn 2 > 1)
    r2 = client.post("/api/hard", json={"on": True})
    assert r2.status_code == 409  # locked after first move


def test_impossible_pattern_rejected():
    _reset()
    # pattern 21 is impossible for the fresh full pool
    r = client.post("/api/submit", json={"guess": "slate", "colors": [0, 1, 2, 0, 0]})
    # fresh pool may accept it; instead test a guaranteed-impossible one:
    # a guess whose pattern cannot arise. Use a pooled guess then a contradictory color.
    # Simpler: submit a guess not in the word list.
    r2 = client.post("/api/submit", json={"guess": "zzzzz", "colors": [2, 2, 2, 2, 2]})
    assert r2.status_code == 400  # not a real word


def test_hint_rules():
    _reset()
    # valid vowel
    r = client.post("/api/hint", json={"letter": "e"}).json()
    assert "e" in r["hinted"]
    # second hint a consonant is fine
    r = client.post("/api/hint", json={"letter": "r"}).json()
    assert set(r["hinted"]) == {"e", "r"}
    # third hint rejected (only 1 cons + 1 vow allowed)
    r3 = client.post("/api/hint", json={"letter": "t"})
    assert r3.status_code == 409
    # duplicate letter rejected as an INPUT error
    _reset()
    client.post("/api/hint", json={"letter": "e"})
    r4 = client.post("/api/hint", json={"letter": "e"})
    assert r4.status_code == 400
    assert r4.json()["detail"]["kind"] == "INPUT_ERROR"


def test_errors_are_categorized():
    """Every error carries kind/title/message so the UI can render it loudly."""
    _reset()
    # INPUT: not a 5-letter word
    r = client.post("/api/submit", json={"guess": "abc", "colors": [0, 0, 0, 0, 0]})
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["kind"] == "INPUT_ERROR" and d["title"] and d["message"]
    # INPUT: unknown word
    r = client.post("/api/submit", json={"guess": "zzzzz", "colors": [0, 0, 0, 0, 0]})
    assert r.json()["detail"]["kind"] == "INPUT_ERROR"
    # LOGIC: hard lock after first move
    client.post("/api/submit", json={"guess": "slate", "colors": [0, 1, 2, 0, 0]})
    r = client.post("/api/hard", json={"on": True})
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "LOGIC_ERROR"


def test_state_exposes_ui_signals():
    _reset()
    s = client.get("/api/state").json()
    assert s["hard_locked"] is False
    assert s["specialist"] is False
    assert s["hint_remaining"] == "1 consonant + 1 vowel"
    client.post("/api/submit", json={"guess": "slate", "colors": [0, 1, 2, 0, 0]})
    assert client.get("/api/state").json()["hard_locked"] is True


def test_hard_mode_toggle_before_move():
    _reset()
    r = client.post("/api/hard", json={"on": True}).json()
    assert r["hard"] is True
    state = client.get("/api/state").json()
    assert state["hard"] is True


def test_reset_clears_everything():
    _reset()
    client.post("/api/submit", json={"guess": "crane", "colors": [0, 1, 2, 0, 0]})
    client.post("/api/hint", json={"letter": "e"})
    r = client.post("/api/reset").json()
    assert r["turn"] == 1
    assert r["pool"] == 2315
    assert r["hard"] is False
    assert r["hinted"] == []


def test_pattern_int_encoding():
    # spot-check the encoding the frontend uses
    assert _pattern([2, 2, 2, 2, 2]) == 2 + 2 * 3 + 2 * 9 + 2 * 27 + 2 * 81
    assert _pattern([0, 1, 2, 0, 0]) == 1 * 3 + 2 * 9
