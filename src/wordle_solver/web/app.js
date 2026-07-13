"use strict";

/* Wordle Strat-Console — DOM controller.
 * Talks to the FastAPI backend at /api/*. All authoritative game state comes
 * from the server; this module only renders it and collects user input.
 *
 * Interaction model (matches real Wordle):
 *   - The GAME BOARD's active row IS the live entry surface. As you type a
 *     5-letter guess, the letters appear on that row.
 *   - Each tile on the active row is clickable: cycle absent -> present ->
 *     correct to record the color from your real Wordle feedback.
 *   - SUBMIT sends the 5 colors to the backend. On success the row locks in
 *     as history; on a 409 (impossible pattern) the row stays editable so you
 *     can fix the colors. No separate, disconnected tile area exists, so
 *     nothing goes "stale". */

const COLORS = ["state-0", "state-1", "state-2"];
const STATE_NAMES = ["absent", "present", "correct"];

class App {
  constructor() {
    this.history = [];        // [{guess, colors:[5]}]
    this.entryColors = [0, 0, 0, 0, 0];
    this.typed = "";          // live entry buffer (max 5), shown on the board
    this.busy = false;
    this.solved = false;
    this.suggestionCache = null;
    this._bind();
    this._renderBoard();   // paint the empty board immediately, before the
                           // async /api/state fetch — otherwise the board is
                           // blank on load until the network round-trip lands
                           // (WebView2 made this gap visible).
    this._buildKeyboard(); // on-screen A–Z keyboard under the board
    this.refresh();
  }

  $(id) { return document.getElementById(id); }

  _bind() {
    // Global keyboard: letters append to the board, Backspace deletes the
    // last letter, Enter submits. Letters/Backspace are ignored while busy or
    // solved; Enter is always allowed to reach submitMove (which itself shows
    // a clear "Already solved" / "No guesses left" notice when appropriate).
    // Ignored while an <input> (hint box) is focused, and we never intercept
    // browser shortcuts (Ctrl/Meta/Alt). No app-level keybindings.
    document.addEventListener("keydown", (e) => {
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;  // leave browser shortcuts alone
      if (e.key === "Enter") {
        e.preventDefault();
        this.submitMove();
        return;
      }
      if (this.busy || this.solved) return;
      if (/^[a-zA-Z]$/.test(e.key)) {
        e.preventDefault();
        this._appendLetter(e.key.toUpperCase());
      } else if (e.key === "Backspace") {
        e.preventDefault();
        this._deleteLetter();
      }
    });
    this.$("hint-btn").addEventListener("click", () => this.logHint());
    this.$("hint-letter").addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.logHint();
    });
    this.$("reset").addEventListener("click", () => this.reset());
    this.$("exit").addEventListener("click", () => this.exitApp());
    this.$("hard").addEventListener("change", (e) => this.toggleHard(e.target.checked));
  }

  // ── entry buffer ───────────────────────────────────────────
  _appendLetter(ch) {
    if (this.busy || this.solved) return;
    if (this.typed.length >= 5) return;
    this.typed += ch;
    this._renderBoard();
  }

  _deleteLetter() {
    if (this.busy || this.solved) return;
    this.typed = this.typed.slice(0, -1);
    this._renderBoard();
  }

  // ── on-screen keyboard ─────────────────────────────────
  // Tapping a letter appends it to the active guess (max 5) if a move is
  // still legal. ENTER submits; DELETE removes the last letter — mirroring
  // the physical keyboard. A brief "pressed" animation plays (mobile-style)
  // but keys are never left dimmed. The board is the single entry surface.
  _buildKeyboard() {
    const kb = this.$("keyboard");
    if (!kb) return;
    kb.innerHTML = "";
    const rows = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];
    rows.forEach((rowLetters) => {
      const row = document.createElement("div");
      row.className = "kb-row";
      rowLetters.split("").forEach((ch) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "key";
        b.textContent = ch;
        b.dataset.letter = ch;
        b.addEventListener("click", () => this._typeLetter(ch, b));
        row.appendChild(b);
      });
      kb.appendChild(row);
    });
    // Action keys: ENTER (submit) + DELETE (backspace) — each with its own
    // identity: DELETE is a subtle destructive key, ENTER the green "go" key.
    const actions = document.createElement("div");
    actions.className = "kb-row kb-actions";
    const del = document.createElement("button");
    del.type = "button";
    del.className = "key key-action key-del";
    del.innerHTML = '<span class="ka-ico">⌫</span><span class="ka-lbl">DELETE</span>';
    del.setAttribute("aria-label", "Delete last letter");
    del.addEventListener("click", () => this._deleteLetter());
    const enter = document.createElement("button");
    enter.type = "button";
    enter.className = "key key-action key-enter";
    enter.innerHTML = '<span class="ka-lbl">ENTER</span><span class="ka-ico">↵</span>';
    enter.setAttribute("aria-label", "Submit guess");
    enter.addEventListener("click", () => this.submitMove());
    actions.appendChild(del);
    actions.appendChild(enter);
    kb.appendChild(actions);
  }

  _typeLetter(ch, btn) {
    this._appendLetter(ch);
    if (btn) {
      btn.classList.add("pressed");
      setTimeout(() => btn.classList.remove("pressed"), 110);
    }
  }

  // ── board rendering ───────────────────────────────────────
  // The active row = the entry surface. It shows the typed letters and is
  // clickable to set colors. History rows are locked. Future rows are empty.
  _renderBoard() {
    const board = this.$("board");
    const n = this.history.length;
    const active = !this.solved && n < 6;
    const typed = this.typed;

    board.innerHTML = "";
    for (let r = 0; r < 6; r++) {
      const row = document.createElement("div");
      row.className = "row";
      row.dataset.row = r;
      if (r < n) {
        const { guess, colors } = this.history[r];
        for (let c = 0; c < 5; c++) {
          row.appendChild(this._tile(guess[c], colors[c], false));
        }
      } else if (r === n && active) {
        row.classList.add("active");
        for (let c = 0; c < 5; c++) {
          row.appendChild(this._activeTile(c, typed[c] || "", this.entryColors[c]));
        }
      } else {
        for (let c = 0; c < 5; c++) {
          row.appendChild(this._tile("", 0, false, true));
        }
      }
      board.appendChild(row);
    }
  }

  _tile(letter, state, active, empty = false) {
    const t = document.createElement("div");
    t.className = "tile" + (empty ? "" : " " + COLORS[state]);
    if (empty) t.classList.add("empty");
    t.textContent = letter;
    return t;
  }

  _activeTile(idx, letter, state) {
    const t = this._tile(letter, state, true);
    t.classList.add("entry");
    t.dataset.idx = idx;
    t.setAttribute("role", "button");
    t.setAttribute("aria-label", `tile ${idx + 1}, ${STATE_NAMES[state]}`);
    t.addEventListener("click", () => {
      if (this.busy || this.solved) return;
      this.entryColors[idx] = (this.entryColors[idx] + 1) % 3;
      this._renderBoard();
    });
    return t;
  }

  // ── server calls ──────────────────────────────────────────
  async refresh() {
    const st = await this._get("/api/state");
    this._renderState(st);
  }

  async _get(url) {
    const res = await fetch(url);
    return res.json();
  }

  async _post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // FastAPI wraps our categorized error in {detail:{kind,title,message}}.
      const d = data.detail;
      const err = new Error((d && d.message) || d || res.statusText);
      err.status = res.status;
      err.kind = (d && d.kind) || "ERROR";
      err.title = (d && d.title) || "Request failed";
      throw err;
    }
    return data;
  }

  _renderState(st) {
    document.documentElement.dataset.appReady = "1";
    this.solved = st.solved;
    this.$("chip-pool-n").textContent = st.pool;
    this.$("chip-turn-n").textContent = st.turn;
    const mode = this.$("chip-mode");
    mode.textContent = st.hard ? "HARD" : "NORMAL";
    mode.classList.toggle("hard", st.hard);
    this.$("hint-status").textContent = st.hint_label;

    // Switches (Normal/Hard + hints) are open only before the first guess.
    // The backend locks the domain once turn 1 is submitted; reflect that by
    // disabling the toggle + hint input and marking the toggle as locked.
    const locked = !!st.mode_locked;
    const hard = this.$("hard");
    hard.disabled = locked;
    hard.checked = st.hard;
    this.$("hard-toggle").classList.toggle("locked", locked);
    this.$("hint-letter").disabled = locked;

    // Specialist note: when hard+hints force a single optimal line, the SOLVE
    // list legitimately has one entry — say so, so it doesn't look like a bug.
    const note = this.$("solve-note");
    if (st.specialist) {
      note.textContent = "★ Forced optimal line — pool " + st.pool +
        " steered into a solved cluster; play this exact word.";
      note.classList.remove("hidden");
    } else {
      note.classList.add("hidden");
    }

    this.$("banner").classList.toggle("hidden", !this.solved);

    this._renderBoard();
    this._renderSuggestions("solve-list", st.strat, "score");
    this._renderSuggestions("shred-list", st.cands, "winp");
  }

  async toggleHard(on) {
    // Live Normal/Hard toggle. The backend derives the full domain from this
    // + however many hints are taken before turn 1, switching in real time.
    try {
      const st = await this._post("/api/hard", { on });
      this.history = [];
      this.entryColors = [0, 0, 0, 0, 0];
      this.solved = false;
      this.typed = "";
      this.$("hint-letter").value = "";
      this._renderBoard();
      this._renderState(st);
      this.clearAlert();
      this.alert("INFO", on ? "Hard mode ON" : "Normal mode ON",
        on ? "Suggestions restricted to the live pool." :
            "Suggestions may use any word for maximum information.");
    } catch (err) {
      this.$("hard").checked = !on;
      this.alertErr(err);
    }
  }

  _renderSuggestions(elId, list, kind) {
    const ol = this.$(elId);
    ol.innerHTML = "";
    list.forEach((d, i) => {
      const li = document.createElement("li");
      li.className = "sugg" + (i === 0 ? " top" : "");
      const word = (d.word || "").toUpperCase();
      const metric = kind === "score"
        ? (d.score ?? 0).toFixed(2)
        : ((d.win_prob ?? 0) * 100).toFixed(1) + "%";
      const pct = kind === "score"
        ? Math.min(100, (d.score ?? 0) * 100)
        : (d.win_prob ?? 0) * 100;
      li.innerHTML =
        `<span class="rank">${i + 1}</span>` +
        `<span class="word">${word}</span>` +
        `<span class="track"><span class="bar" style="width:${Math.max(4, pct).toFixed(0)}%"></span></span>` +
        `<span class="metric">${metric}</span>`;
      ol.appendChild(li);
    });
  }

  // ── actions ────────────────────────────────────────────────
  async submitMove() {
    if (this.busy) return;
    // Coherence guards: a submit with no valid entry row must explain WHY,
    // never fall through to a misleading "not a 5-letter word" error.
    if (this.solved) {
      this.alert("INFO", "Already solved", "Hit SYSTEM RESET to play again.");
      return;
    }
    if (!document.querySelector(".board .row.active")) {
      this.alert("INFO", "No guesses left", "All 6 rows are used — hit SYSTEM RESET.");
      return;
    }
    const guess = this.typed;
    if (guess.length !== 5) {
      this.alert("INPUT_ERROR", "Not a 5-letter word",
        "Type exactly five letters before submitting.");
      return;
    }
    this.busy = true;
    const intel = this.$("card-intel");
    if (intel) intel.classList.add("calculating");  // reassure: engine is solving, not frozen
    try {
      const st = await this._post("/api/submit", { guess, colors: this.entryColors.slice() });
      this.history.push({ guess, colors: this.entryColors.slice() });
      this.entryColors = [0, 0, 0, 0, 0];
      this.typed = "";
      this._renderBoard();
      this._renderState(st);
      this.clearAlert();
      if (st.solved) this.alert("SUCCESS", "Solved!", `${guess} in ${st.turn} — nice.`);
    } catch (err) {
      // Row stays editable on any failure so the user can fix colors/word.
      this.alertErr(err);
    } finally {
      this.busy = false;
      if (intel) intel.classList.remove("calculating");
    }
  }

  async logHint() {
    const el = this.$("hint-letter");
    const letter = (el.value || "").toUpperCase();
    if (!letter) {
      this.alert("INPUT_ERROR", "No hint letter", "Type a single letter A–Z first.");
      return;
    }
    try {
      const st = await this._post("/api/hint", { letter });
      el.value = "";
      this._renderState(st);
      this.clearAlert();
      this.alert("SUCCESS", "Hint logged",
        `${letter} recorded — hint state: ${st.hint_remaining}.`);
    } catch (err) {
      this.alertErr(err);
    }
  }

  async reset() {
    try {
      const st = await this._post("/api/reset");
      this.history = [];
      this.entryColors = [0, 0, 0, 0, 0];
      this.solved = false;
      this.typed = "";
      this.$("hint-letter").value = "";
      this._renderBoard();
      this._renderState(st);
      this.clearAlert();
      this.alert("INFO", "New game", "Pick a mode to start a fresh puzzle.");
    } catch (err) {
      this.alertErr(err);
    }
  }

  // App-driven, graceful exit: hands off to the native host, which shows the
  // closing splash and frees the backend port. Falls back to a plain close if
  // the host API isn't wired (e.g. running the web UI outside the desktop exe).
  exitApp() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.exit_app) {
      window.pywebview.api.exit_app();
    } else {
      this.alert("INFO", "Exit", "Close this tab/window to quit.");
    }
  }

  // ── loud, categorized alerts ───────────────────────────────
  // Kinds: INPUT_ERROR (red), LOGIC_ERROR (amber), SUCCESS (green),
  // INFO (blue). Errors persist until the next action; info/success
  // auto-dismiss so they don't pile up.
  alert(kind, title, message) {
    const box = this.$("alert");
    const k = kind.toLowerCase().replace("_error", "");
    box.className = "alert alert-" + k;
    box.innerHTML =
      `<span class="alert-tag">${kind.replace("_", " ")}</span>` +
      `<span class="alert-title">${title}</span>` +
      `<span class="alert-msg">${message}</span>`;
    box.classList.remove("hidden");
    clearTimeout(this._alertTimer);
    const transient = kind === "SUCCESS" || kind === "INFO";
    if (transient) {
      this._alertTimer = setTimeout(() => box.classList.add("hidden"), 3500);
    }
  }

  alertErr(err) {
    this.alert(err.kind || "ERROR", err.title || "Error",
      err.message || "Something went wrong.");
  }

  clearAlert() {
    // only clear sticky (error) alerts; leave transient ones to time out
    const box = this.$("alert");
    if (box.classList.contains("alert-input") || box.classList.contains("alert-logic")) {
      box.classList.add("hidden");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => { window.app = new App(); });
