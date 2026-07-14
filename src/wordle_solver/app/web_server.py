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
import sys
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from wordle_solver.engine import WordleEngine
from pathlib import Path

from wordle_solver.utils import web_path
from wordle_solver.engine.modes import VOWELS, CONSONANTS
from wordle_solver.engine.game_mode import GameMode, FlowError, MAX_HINTS

WEB_DIR = Path(web_path(""))

MAX_HINTS = 2  # NYT rule: exactly one consonant AND one vowel

# Back-compat shim: the desktop app and dev server call configure_engine()
# to bind a per-instance port. The turn-1 cache is in-memory only (see
# engine._load_turn1_cache), so there is nothing to bind — keep the call a
# harmless no-op so existing boot code keeps working.
def configure_engine(port: int) -> None:
    return None


# State the frontend can never derive on its own (the engine is the
# source of truth; we only echo what it tells us, plus the minimal
# view state the UI needs to render controls).
app = FastAPI(title="Wordle Strat-Console")
engine = WordleEngine()

# ── locked 6-mode flow controller ────────────────────────────────────────
# A single GameMode instance owns the mode lock + hint budget for the current
# game. It is (re)created by POST /api/start with one of the six mode keys;
# until then no play is possible. The engine is bound to it via set_mode so
# specialist dispatch + scoring are driven by the locked domain spec.
game_mode: GameMode | None = None

# ── clean-shutdown signalling ────────────────────────────────────────────────
# A request to POST /api/shutdown (or the desktop app closing) sets this flag;
# the dev server's watchdog observes it and stops the uvicorn loop. Kept at
# module level (registered before the root StaticFiles mount) so the route is
# never shadowed by the static mount.
shutdown_requested = False


def request_shutdown() -> None:
    """Flag the running server to stop at the next watchdog tick."""
    global shutdown_requested
    shutdown_requested = True


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
    if game_mode is None:
        # No interaction yet — the domain DEFAULTS to normal 0 hints. Show a
        # populated, ready board so the UI is alive on load.
        engine.set_mode("normal_0")
        strat, cands = engine.get_suggestions(is_hard_mode=False)
        _idx0 = engine.possible_indices.tolist()
        _words0 = [engine.lex.solution_words[i] for i in _idx0[:400]]
        return {
            "turn": 1, "pool": int(engine.possible_indices.size),
            "hard": False, "mode": "normal_0", "mode_locked": False,
            "hint_budget": MAX_HINTS, "hinted": [],
            "hint_label": "OPTIONAL hint: reveal 1 consonant + 1 vowel",
            "hint_remaining": "1 consonant + 1 vowel",
            "strat": strat[:12], "cands": cands[:12],
            "full_pool": _words0, "pool_total": int(engine.possible_indices.size),
            "specialist": False, "solved": False, "started": False,
        }
    gm = game_mode
    # The engine domain is DERIVED from the user's Normal/Hard choice + the
    # number of hints taken. Keep the engine bound to that derived domain.
    engine.set_mode(gm.mode_key)
    strat, cands = engine.get_suggestions(is_hard_mode=gm.hard)
    hinted = sorted(engine.hinted_letters)
    hint_label = _hint_label(hinted, gm.hint_budget)
    pool = int(engine.possible_indices.size)
    specialist = bool(gm.hard and engine.hinted_letters and len(strat) == 1
                      and pool > 1)
    # Full remaining candidate pool — exposed so the UI can let the human pick
    # ANY legal answer (the solver recommends; the human decides). Capped at
    # 400 rendered rows; pool_total carries the true count for "and N more".
    _idx = engine.possible_indices.tolist()
    _words = [engine.lex.solution_words[i] for i in _idx[:400]]
    return {
        "turn": gm.turn,  # 1-based: turn 1 = first guess yet to be made
        "pool": pool,
        "hard": gm.hard,
        "mode": gm.spec.key,
        "mode_locked": gm.mode_locked,    # False before turn 1, True after
        "hint_budget": gm.hint_budget,
        "hinted": hinted,
        "hint_label": hint_label,
        "hint_remaining": _hint_remaining(hinted, gm.hint_budget),
        "strat": strat[:12],
        "cands": cands[:12],
        "full_pool": _words,
        "pool_total": pool,
        "specialist": specialist,
        "solved": gm.over and _is_win(),
        "started": True,
    }


def _is_win() -> bool:
    """Win = all five tiles green. The board tracks this via update_state;
    we approximate the sticky win flag from the engine + a solved pool of 1
    that equals the last guess. The frontend records the explicit win on
    submit, so we mirror it here through the game_mode flag."""
    return getattr(game_mode, "_won", False)


def _hint_remaining(hinted: list[str], budget: int) -> str:
    """Human phrase for what the hint workflow still accepts (or 'complete')."""
    if len(hinted) >= budget:
        return "complete"
    vowels = {c for c in hinted if c in VOWELS}
    cons = {c for c in hinted if c in CONSONANTS}
    need = []
    if len(cons) == 0 and len(hinted) < budget:
        need.append("1 consonant")
    if len(vowels) == 0 and len(hinted) < budget:
        need.append("1 vowel")
    return " + ".join(need) if need else "complete"


def _hint_label(hinted: list[str], budget: int) -> str:
    if not hinted:
        if budget == 0:
            return "No hints in this mode"
        return "OPTIONAL hint: reveal 1 consonant + 1 vowel"
    vowels = {c for c in hinted if c in VOWELS}
    cons = {c for c in hinted if c in CONSONANTS}
    if len(hinted) >= budget:
        return f"KNOWN: {', '.join(h.upper() for h in hinted)} — complete"
    if vowels and cons:
        return f"KNOWN: {', '.join(h.upper() for h in hinted)} — complete"
    if vowels and len(cons) == 0:
        return f"KNOWN: {', '.join(h.upper() for h in hinted)} — need 1 consonant"
    return f"KNOWN: {', '.join(h.upper() for h in hinted)} — need 1 vowel"


# ── API ─────────────────────────────────────────────────────────────────────
def _ensure_game() -> "GameMode":
    """Lazily establish the default domain (normal_0) on first interaction.

    The domain DEFAULTS to normal 0 hints. Toggling Hard or logging a hint
    live-switches the domain (normal_0 -> hard_0, or 0-hint -> 1/2 hints);
    everything locks after the first guess. No explicit "start" call needed.
    Returns the live (non-None) GameMode.
    """
    global game_mode
    if game_mode is None:
        engine.reset()
        game_mode = GameMode()  # normal_0 by default
    return game_mode


class HardReq(BaseModel):
    on: bool  # Normal/Hard toggle. Live before turn 1; locked after.


@app.post("/api/hard")
def toggle_hard(req: HardReq) -> dict:
    """Live Normal/Hard toggle. Switches the derived domain in real time
    (normal_0 <-> hard_0) WITHOUT wiping any hints already taken. Refused
    once the mode is locked (after the first guess)."""
    gm = _ensure_game()
    if gm.over:
        raise _err(409, "LOGIC_ERROR", "Game already over",
                   "This game is finished. Hit SYSTEM RESET to play again.")
    try:
        gm.toggle_hard(req.on)
    except FlowError as e:
        raise _err(409, "LOGIC_ERROR", "Mode locked", e.message)
    return _state()


@app.get("/api/state")
def get_state() -> dict:
    return _state()


@app.post("/api/submit")
def submit_move(move: Move) -> dict:
    global game_mode
    gm = _ensure_game()
    if gm.over:
        raise _err(409, "LOGIC_ERROR", "Game already over",
                   "This game is finished. Hit SYSTEM RESET to play again.")
    guess = move.guess.strip().lower()
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
    won = move.colors == [2, 2, 2, 2, 2]
    gm.on_submit(won)  # locks the mode + records win/over
    state = _state()
    state["last_guess"] = guess
    state["solved"] = won
    return state


@app.post("/api/hint")
def log_hint(hint: Hint) -> dict:
    gm = _ensure_game()
    if gm.over:
        raise _err(409, "LOGIC_ERROR", "Game already over",
                   "This game is finished. Reset to start a new game.")
    letter = hint.letter.strip().lower()
    # Enforce the locked-mode + NYT hint rule centrally through GameMode.
    try:
        gm.add_hint(letter)
    except FlowError as e:
        if e.code == "GAME_OVER":
            raise _err(409, "LOGIC_ERROR", "Game over", e.message)
        if e.code == "MODE_LOCKED":
            raise _err(409, "LOGIC_ERROR", "Hints locked", e.message)
        if e.code == "HINT_RULE":
            # Map to the precise reason the user can act on.
            if "vowel" in e.message:
                raise _err(409, "LOGIC_ERROR", "Vowel already set", e.message)
            if "consonant" in e.message:
                raise _err(409, "LOGIC_ERROR", "Consonant already set", e.message)
            if "already logged" in e.message:
                raise _err(400, "INPUT_ERROR", "Already logged", e.message)
            raise _err(409, "LOGIC_ERROR", "Hints full", e.message)
        raise _err(400, "INPUT_ERROR", "Not a letter", e.message)
    # Commit the validated hint to the engine (it applies the pruning).
    if not engine.add_hint(letter):
        # Should be unreachable: GameMode validated the same rule, but the
        # engine ALSO checks the hint doesn't empty the pool. Surface it.
        raise _err(409, "LOGIC_ERROR", "Hint eliminates every answer",
                   f"No remaining answer contains '{letter.upper()}'. "
                   "That hint contradicts your guesses so far.")
    return _state()


@app.post("/api/reset")
def reset() -> dict:
    global game_mode
    engine.reset()
    game_mode = None
    return _state()


@app.post("/api/shutdown")
def shutdown() -> dict:
    """Ask the dev server to stop. The desktop app calls this on window
    close; the dev server's watchdog observes ``shutdown_requested`` and
    exits the uvicorn loop (releasing the matrix mmap)."""
    request_shutdown()
    return {"ok": True}


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
