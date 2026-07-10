"""Wordle Strat-Console — web backend.

A thin FastAPI wrapper around the already-verified ``Engine``. It owns a
single :class:`Engine.WordleEngine` instance and exposes a small JSON API
that the DOM frontend (``web/``) drives. There is no canvas: the UI is
plain semantic HTML, so it is fully scrapeable and testable.

The color model is identical to the Flet GUI and to the NYT Wordle
feedback convention the user enters by hand:

    state 0 = absent   (grey)
    state 1 = present  (yellow)
    state 2 = correct  (green)

A submitted move encodes the five states as
``pattern = sum(state[i] * 3**i)`` and calls ``engine.update_state``.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import Engine

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"

MAX_HINTS = 2  # NYT rule: exactly one consonant AND one vowel

# State the frontend can never derive on its own (the engine is the
# source of truth; we only echo what it tells us, plus the minimal
# view state the UI needs to render controls).
app = FastAPI(title="Wordle Strat-Console")
engine = Engine.WordleEngine()
hard_mode = False  # local flag mirrored into get_suggestions(is_hard_mode=...)
won_flag = False   # sticky win state so the banner survives a page refresh


# ── request / response models ───────────────────────────────────────────────
class Move(BaseModel):
    guess: str
    # five integers in {0,1,2}; index 0 = leftmost tile
    colors: list[int] = Field(..., min_length=5, max_length=5)


class Hint(BaseModel):
    letter: str


def _pattern_int(colors: list[int]) -> int:
    return sum(c * (3 ** i) for i, c in enumerate(colors))


def _err(status: int, kind: str, title: str, message: str) -> HTTPException:
    """Categorized, loud error. `kind` is INPUT_ERROR (the user typed/clicked
    something invalid) or LOGIC_ERROR (the request is well-formed but
    contradicts the game state). The frontend renders kind+title+message as a
    prominent, attention-grabbing alert."""
    return HTTPException(status_code=status,
                         detail={"kind": kind, "title": title, "message": message})


def _state() -> dict:
    strat, cands = engine.get_suggestions(is_hard_mode=hard_mode)
    hinted = sorted(engine.hinted_letters)
    hint_label = _hint_label(hinted)
    pool = int(engine.possible_indices.size)
    # The residual specialist returns a single forced-optimal guess when hard
    # mode + NYT hints steer the pool into a precomputed cluster. Surfacing a
    # note stops the 1-item SOLVE list from reading like "pool pruned to 1".
    specialist = bool(hard_mode and engine.hinted_letters and len(strat) == 1
                      and pool > 1)
    return {
        "turn": engine.turn,  # 1-based: turn 1 = first guess yet to be made
        "pool": pool,
        "hard": hard_mode,
        "hard_locked": engine.turn > 1,  # frontend shows an X on the toggle
        "hinted": hinted,
        "hint_label": hint_label,
        "hint_remaining": _hint_remaining(hinted),
        "strat": strat[:12],
        "cands": cands[:12],
        "specialist": specialist,
        "won": won_flag,
        "solved": won_flag,
    }


def _hint_remaining(hinted: list[str]) -> str:
    """Human phrase for what the hint workflow still accepts (or 'complete')."""
    vowels = {c for c in hinted if c in Engine.VOWELS}
    cons = {c for c in hinted if c in Engine.CONSONANTS}
    need = []
    if not cons:
        need.append("1 consonant")
    if not vowels:
        need.append("1 vowel")
    return " + ".join(need) if need else "complete"


def _hint_label(hinted: list[str]) -> str:
    if not hinted:
        return "need 1 CONSONANT + 1 VOWEL"
    vowels = {c for c in hinted if c in Engine.VOWELS}
    cons = {c for c in hinted if c in Engine.CONSONANTS}
    if vowels and cons:
        return f"KNOWN: {', '.join(h.upper() for h in hinted)} — complete"
    if vowels and not cons:
        return f"KNOWN: {', '.join(h.upper() for h in hinted)} — need 1 CONSONANT"
    return f"KNOWN: {', '.join(h.upper() for h in hinted)} — need 1 VOWEL"


# ── API ─────────────────────────────────────────────────────────────────────
@app.get("/api/state")
def get_state() -> dict:
    return _state()


@app.post("/api/submit")
def submit_move(move: Move) -> dict:
    global hard_mode, won_flag
    guess = move.guess.strip().lower()
    if won_flag:
        raise _err(409, "LOGIC_ERROR", "Game already solved",
                   "The puzzle is solved. Hit SYSTEM RESET to play again.")
    if engine.turn > 6:
        raise _err(409, "LOGIC_ERROR", "Out of turns",
                   "All 6 guesses are used. Hit SYSTEM RESET to play again.")
    if len(guess) != 5 or not guess.isalpha():
        raise _err(400, "INPUT_ERROR", "Not a 5-letter word",
                   f"'{move.guess.strip().upper() or '(empty)'}' isn't 5 letters. "
                   "Type exactly five letters A–Z.")
    if guess not in engine.word_to_idx:
        raise _err(400, "INPUT_ERROR", "Unknown word",
                   f"'{guess.upper()}' isn't in the Wordle word list. "
                   "Check your spelling.")
    if any(c not in (0, 1, 2) for c in move.colors):
        raise _err(400, "INPUT_ERROR", "Bad tile colors",
                   "Each tile must be grey, yellow, or green.")

    pat = _pattern_int(move.colors)
    ok = engine.update_state(guess, pat)
    if not ok:
        raise _err(
            409, "LOGIC_ERROR", "Impossible feedback",
            f"No remaining answer gives '{guess.upper()}' that exact color "
            "pattern. Re-check each tile's color"
            + (" (an active hint also restricts the pool)."
               if engine.hinted_letters else "."))
    won_flag = move.colors == [2, 2, 2, 2, 2]
    state = _state()
    state["last_guess"] = guess
    state["won"] = won_flag
    return state


@app.post("/api/hint")
def log_hint(hint: Hint) -> dict:
    letter = hint.letter.strip().lower()
    if won_flag:
        raise _err(409, "LOGIC_ERROR", "Game already solved",
                   "The puzzle is solved. Reset to start a new game.")
    if len(letter) != 1 or not letter.isalpha():
        raise _err(400, "INPUT_ERROR", "Not a single letter",
                   f"'{hint.letter.strip().upper() or '(empty)'}' isn't one "
                   "letter A–Z. Enter a single hint letter.")
    if letter in engine.hinted_letters:
        raise _err(400, "INPUT_ERROR", "Already logged",
                   f"You already logged the hint '{letter.upper()}'.")
    nv, nc, total = Engine._hint_counts(engine.hinted_letters)
    if total >= Engine.MAX_HINTS:
        raise _err(409, "LOGIC_ERROR", "Hints full",
                   "NYT gives exactly 1 consonant + 1 vowel. Both are logged.")
    if letter in Engine.VOWELS and nv >= 1:
        raise _err(409, "LOGIC_ERROR", "Vowel already set",
                   "Only one vowel hint is allowed. Log a consonant instead.")
    if letter in Engine.CONSONANTS and nc >= 1:
        raise _err(409, "LOGIC_ERROR", "Consonant already set",
                   "Only one consonant hint is allowed. Log a vowel instead.")
    ok = engine.add_hint(letter)
    if not ok:
        raise _err(409, "LOGIC_ERROR", "Hint eliminates every answer",
                   f"No remaining answer contains '{letter.upper()}'. "
                   "That hint contradicts your guesses so far.")
    return _state()


@app.post("/api/hard")
def set_hard(payload: dict | None = None) -> dict:
    global hard_mode, won_flag
    want = (not hard_mode if not (isinstance(payload, dict) and "on" in payload)
            else bool(payload["on"]))
    # Hard mode is a pre-game commitment: it can only change on turn 1.
    if engine.turn > 1 and want != hard_mode:
        raise _err(409, "LOGIC_ERROR", "Hard mode is locked",
                   "Hard mode can only be set before your first guess. "
                   "Reset to change it.")
    hard_mode = want
    return _state()


@app.post("/api/reset")
def reset() -> dict:
    global hard_mode, won_flag
    engine.reset()
    hard_mode = False
    won_flag = False
    return _state()


# ── static frontend ─────────────────────────────────────────────────────────
@app.middleware("http")
async def _no_store(request, call_next):
    """WebView2 caches assets by URL across launches and will serve a stale
    app.js/index.html without re-fetching. Force revalidation so a rebuilt
    exe always renders the current frontend."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


# Boot status channel for the desktop splash: the loader (desktop_app.py)
# pushes milestone text here; the splash polls it. Defined BEFORE the root
# StaticFiles mount so the mount can't shadow it.
_load_status = {"text": "Booting engine…"}


@app.get("/api/load-status")
def load_status():
    return _load_status


def set_load_status(text: str) -> None:
    _load_status["text"] = text


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
