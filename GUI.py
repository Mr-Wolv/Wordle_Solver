"""Wordle Strat-Console — Flet UI (redesigned).

A polished, dark, three-pane operational console for the solver in
``Engine.py``. The engine is the single source of truth for game state;
this view owns only the presentation (board tiles, intel lists, dialogs).

Run:
    python GUI.py                 # native desktop window
    flet pack GUI.py              # build a distributable .exe
"""
from __future__ import annotations

import asyncio
import os
import sys

import flet as ft
from flet import Border, BorderSide, Padding as pad
import Engine as Engine

# ── palette ────────────────────────────────────────────────────────────
BG = "#0a0c11"          # app background (deepest)
PANEL = "#161d2b"       # cards
PANEL2 = "#1f2937"      # inputs / tiles / wells
PANEL3 = "#283447"      # hover / active wells
LINE = "#323d52"        # hairline borders
TEXT = "#eef2f8"        # primary text
SUBTLE = "#9aa4b8"      # secondary text
FAINT = "#7b8499"       # tertiary (still legible)
GREEN = "#34d27b"       # correct (in place)
YELLOW = "#e6c34a"      # present (wrong place)
GREY = "#39414f"        # absent
ACCENT = "#5b9dff"      # brand / interactive
ERROR = "#ff6b6b"
FONT = "Roboto"         # bundled with Flet

# tile state -> (background, letter color)
TILE = {
    0: (GREY, "#c3cad8"),
    1: (YELLOW, "#1c1700"),
    2: (GREEN, "#04230f"),
}
GREEN_TX, YELLOW_TX, GREY_TX = "#04230f", "#1c1700", "#c3cad8"


def _pp(x: float) -> str:
    """Format a probability as a compact percentage."""
    return f"{x * 100:.1f}%"


def _lighten(hexc: str, amt: float = 0.18) -> str:
    """Lighten a #rrggbb color by mixing toward white."""
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * amt)
    g = int(g + (255 - g) * amt)
    b = int(b + (255 - b) * amt)
    return f"#{r:02x}{g:02x}{b:02x}"


class App:
    def __init__(self, page: ft.Page):
        self.page = page
        self.engine = Engine.WordleEngine()
        self.colors = [0, 0, 0, 0, 0]        # current guess tile states
        self.history: list[tuple[str, list[int]]] = []
        self._busy = False
        self._hard = False
        self._solved = False
        self._build()

    # ── control construction ─────────────────────────────────────────
    def _build(self):
        self.page.title = "Wordle Strat-Console"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            scaffold_bgcolor=BG,
        )
        self.page.bgcolor = BG
        self.page.padding = 0
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.vertical_alignment = ft.MainAxisAlignment.START
        self.page.font_family = FONT
        self.page.window_width = 1200
        self.page.window_height = 850
        self.page.window_min_width = 1024
        self.page.window_min_height = 720
        self.page.window_resizable = True

        self.page.add(
            ft.Column(
                [
                    self._header(),
                    ft.Container(content=self._body(), expand=True, padding=16),
                    self._footer(),
                ],
                spacing=0,
                expand=True,
            )
        )
        self._sync_chips()
        self.page.run_task(self.refresh)

    # ── header ──────────────────────────────────────────────────────
    def _header(self):
        self.chip_pool, self.chip_pool_tx = self._chip("POOL 2315", GREEN)
        self.chip_turn, self.chip_turn_tx = self._chip("TURN 0", TEXT)
        self.chip_mode, self.chip_mode_tx = self._chip("NORMAL", ACCENT)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=26, height=26, border_radius=7,
                                gradient=ft.LinearGradient(
                                    begin=ft.Alignment(-1, -1),
                                    end=ft.Alignment(1, 1),
                                    colors=[GREEN, ACCENT]),
                            ),
                            ft.Column(
                                [
                                    ft.Text("WORDLE STRAT-CONSOLE", size=16,
                                            weight=ft.FontWeight.BOLD, color=TEXT),
                                    ft.Text("tactical solver · greedy + residual specialist",
                                            size=10, color=SUBTLE),
                                ], spacing=1,
                            ),
                        ], spacing=10,
                    ),
                    ft.Row([self.chip_pool, self.chip_turn, self.chip_mode], spacing=8),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            bgcolor=PANEL, border=ft.Border(bottom=ft.BorderSide(1, LINE)),
            padding=pad.symmetric(horizontal=20, vertical=12),
        )

    def _chip(self, text, color):
        tx = ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color=color)
        box = ft.Container(
            content=tx, bgcolor=PANEL2, border=ft.Border.all(1, LINE),
            border_radius=14, padding=pad.symmetric(horizontal=12, vertical=6),
        )
        return box, tx

    # ── body (three panes) ──────────────────────────────────────────
    def _body(self):
        return ft.Row(
            [self._board_card(), self._command_card(), self._intel_card()],
            spacing=16, expand=True,
        )

    def _card(self, title, accent=ACCENT, body=None, badge=None):
        head = ft.Row(
            [
                ft.Container(width=3, height=14, border_radius=2, bgcolor=accent),
                ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=SUBTLE),
            ], spacing=8,
        )
        if badge:
            head.controls.append(ft.Container(expand=True))
            head.controls.append(badge)
        content = [head]
        if body is not None:
            content.append(body)
        return ft.Container(
            content=ft.Column(content, spacing=12, expand=True),
            bgcolor=PANEL, border=ft.Border.all(1, LINE), border_radius=16,
            padding=16, expand=True,
        )

    # ── board pane ──────────────────────────────────────────────────
    def _board_card(self):
        self.banner = ft.Container(visible=False)
        self.board = ft.Container()
        self._render_board()
        legend = ft.Row(
            [
                self._legend_item(GREEN, "in place"),
                self._legend_item(YELLOW, "present"),
                self._legend_item(GREY, "absent"),
            ], spacing=14,
        )
        self.hard_switch = ft.Switch(
            label="HARD MODE", value=False,
            active_color=GREEN, thumb_color=TEXT,
            label_text_style=ft.TextStyle(size=11, color=SUBTLE, weight=ft.FontWeight.BOLD),
            on_change=self.on_hard_toggle,
        )
        controls_row = ft.Row(
            [legend, ft.Container(expand=True), self.hard_switch],
            alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        body = ft.Column(
            [self.banner, self.board, ft.Divider(height=1, color=LINE),
             controls_row],
            spacing=12, expand=True,
        )
        return self._card("GAME BOARD", GREEN, body)

    def _legend_item(self, color, label):
        return ft.Row(
            [ft.Container(width=14, height=14, border_radius=4, bgcolor=color,
                          border=ft.Border.all(1, "#ffffff22")),
             ft.Text(label, size=11, color=SUBTLE)], spacing=6,
        )

    def _render_board(self):
        rows = []
        n = len(self.history)
        for r in range(6):
            cells = []
            if r < n:
                word, cols = self.history[r]
                for c in range(5):
                    cells.append(self._cell(word[c].upper(), cols[c], False))
            elif r == n and not self._solved:
                for c in range(5):
                    cells.append(self._active_cell(c))
            else:
                for _ in range(5):
                    cells.append(self._cell("", 0, False, empty=True))
            rows.append(ft.Row(cells, spacing=6))
        self.board.content = ft.Column(rows, spacing=6)
        try:
            self.board.update()
        except RuntimeError:
            pass

    def _cell(self, letter, state, active, empty=False):
        bg, tx = TILE[state]
        if empty:
            return ft.Container(
                width=54, height=54, border_radius=10,
                bgcolor=PANEL2,
                border=ft.Border.all(1, LINE),
                alignment=ft.Alignment(0, 0),
            )
        return ft.Container(
            width=54, height=54, border_radius=10,
            gradient=ft.LinearGradient(
                begin=ft.Alignment(0, -1), end=ft.Alignment(0, 1),
                colors=[_lighten(bg, 0.28), bg]),
            border=ft.Border.all(1, "#ffffff22"),
            alignment=ft.Alignment(0, 0),
            shadow=ft.BoxShadow(blur_radius=6, color="#00000066", offset=ft.Offset(0, 2)),
            content=ft.Text(letter, size=24, weight=ft.FontWeight.BOLD, color=tx),
        )

    def _active_cell(self, idx):
        val = (getattr(self, "input", None) and self.input.value or "") or ""
        letter = val[idx:idx + 1].upper()
        bg, tx = TILE[self.colors[idx]]
        return ft.Container(
            width=50, height=50, border_radius=9, bgcolor=bg,
            alignment=ft.Alignment(0, 0), ink=True, on_click=self._cycle_tile(idx),
            content=ft.Text(letter, size=22, weight=ft.FontWeight.BOLD, color=tx),
            tooltip="click to set result color",
        )

    def _cycle_tile(self, idx):
        def handler(e):
            self.colors[idx] = (self.colors[idx] + 1) % 3
            self._render_board()
        return handler

    # ── command pane ─────────────────────────────────────────────────
    def _command_card(self):
        self.input = ft.TextField(
            hint_text="TYPE A 5-LETTER GUESS", text_align=ft.TextAlign.CENTER,
            text_style=ft.TextStyle(size=22, weight=ft.FontWeight.BOLD, color=TEXT),
            bgcolor=PANEL2, border_color=LINE, border_width=1, height=52,
            on_change=self._on_input, on_submit=self.submit_move, max_length=5,
            counter=ft.Text(""),
        )

        submit = ft.ElevatedButton(
            content=ft.Text("SUBMIT GUESS", size=15, weight=ft.FontWeight.BOLD, color="#04230f"),
            bgcolor=GREEN, height=48, width=300,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
            on_click=self.submit_move,
        )

        # NYT hints
        self.hint_entry = ft.TextField(
            hint_text="A–Z", text_align=ft.TextAlign.CENTER, width=64, height=40,
            text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD, color=TEXT),
            bgcolor=PANEL2, border_color=LINE, border_width=1,
            on_submit=self.log_hint, max_length=1, counter=ft.Text(""),
        )
        self.hint_btn = ft.ElevatedButton(
            content=ft.Text("LOG HINT", size=12, weight=ft.FontWeight.BOLD, color=BG),
            height=40, bgcolor=YELLOW,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=self.log_hint,
        )
        hint_group = ft.Column(
            [
                ft.Text("NYT HINT LETTER", size=10, weight=ft.FontWeight.BOLD, color=SUBTLE),
                ft.Row([self.hint_entry, self.hint_btn], spacing=8),
            ], spacing=4,
        )
        self.hint_label = ft.Text("", size=12, color=SUBTLE, weight=ft.FontWeight.BOLD)
        hint_warn = ft.Text(
            "Some answers need a hint. NYT hint = 1 consonant + 1 vowel (recommended).",
            size=11, color=SUBTLE,
        )
        hint_block = ft.Column(
            [hint_group, self.hint_label, hint_warn], spacing=8,
        )

        body = ft.Column(
            [
                ft.Text("ENTER GUESS", size=12, weight=ft.FontWeight.BOLD, color=SUBTLE),
                self.input,
                submit,
                ft.Divider(height=1, color=LINE),
                ft.Text("EXTERNAL INTEL · NYT HINTS", size=12, weight=ft.FontWeight.BOLD,
                        color=SUBTLE),
                hint_block,
            ], spacing=12, expand=True,
        )
        return self._card("COMMAND", ACCENT, body)

    def _on_input(self, e):
        v = (self.input.value or "").upper()
        if v != self.input.value:
            self.input.value = v
        self._render_board()

    # ── intel pane ───────────────────────────────────────────────────
    def _intel_card(self):
        self.solve_body = ft.Column([], spacing=5, scroll=ft.ScrollMode.AUTO, expand=True)
        self.shred_body = ft.Column([], spacing=5, scroll=ft.ScrollMode.AUTO, expand=True)
        solve_hdr = ft.Row(
            [ft.Text("SOLVE", size=11, weight=ft.FontWeight.BOLD, color=GREEN, width=60),
             ft.Text("top candidate words", size=10, color=FAINT)],
            spacing=8)
        shred_hdr = ft.Row(
            [ft.Text("SHRED", size=11, weight=ft.FontWeight.BOLD, color=YELLOW, width=60),
             ft.Text("high-frequency openers", size=10, color=FAINT)],
            spacing=8)
        solve_sec = ft.Container(content=ft.Column([solve_hdr, self.solve_body], spacing=6),
                                 expand=1)
        shred_sec = ft.Container(content=ft.Column([shred_hdr, self.shred_body], spacing=6),
                                 expand=1)
        body = ft.Column([solve_sec, ft.Divider(height=1, color=LINE), shred_sec],
                         spacing=10, expand=True)
        return self._card("INTEL", YELLOW, body)

    def _sugg_row(self, d, idx, top=False, kind="solve"):
        word = d["word"].upper()
        if kind == "solve":
            metric = float(d.get("score") or 0.0)
            label = f"{metric:.2f}"
            bar_w = max(6, int(min(metric / 6.0, 1.0) * 230))
            bar_color = GREEN if top else ACCENT
        else:
            metric = float(d.get("win_prob") or 0.0)
            label = _pp(metric)
            bar_w = max(6, int(min(metric / 0.05, 1.0) * 230))
            bar_color = YELLOW
        rank_tx = ft.Text(str(idx + 1), size=11, weight=ft.FontWeight.BOLD,
                          color=(GREEN if top else FAINT), width=16,
                          text_align=ft.TextAlign.CENTER)
        row = ft.Container(
            content=ft.Row(
                [
                    rank_tx,
                    ft.Text(word, size=14, weight=ft.FontWeight.BOLD,
                            color=(GREEN if top else TEXT), width=78),
                    ft.Container(height=6, width=bar_w, border_radius=3, bgcolor=bar_color),
                    ft.Text(label, size=11, color=SUBTLE, width=56,
                            text_align=ft.TextAlign.RIGHT),
                ], spacing=8,
            ),
            padding=pad.symmetric(vertical=4, horizontal=8),
            border_radius=8,
            bgcolor=PANEL2 if top else None,
        )
        return row

    # ── engine wiring ────────────────────────────────────────────────
    def _sync_chips(self):
        pool = len(self.engine.possible_indices)
        self.chip_pool_tx.value = f"POOL {pool}"
        self.chip_pool_tx.color = GREEN if pool > 0 else ERROR
        self.chip_turn_tx.value = f"TURN {self.engine.turn - 1}"
        self.chip_mode_tx.value = "HARD" if self._hard else "NORMAL"
        self.chip_mode_tx.color = ERROR if self._hard else ACCENT
        for c in (self.chip_pool, self.chip_turn, self.chip_mode):
            try:
                c.update()
            except RuntimeError:
                pass

    async def refresh(self):
        if self._busy:
            return
        self._busy = True
        self.chip_pool_tx.value = "CALCULATING…"
        self.chip_pool_tx.color = YELLOW
        self.chip_pool.update()
        try:
            strat, cands = await asyncio.to_thread(
                self.engine.get_suggestions, self._hard)
            self._render_intel(strat, cands)
        finally:
            self._busy = False
            self._sync_chips()
            self.page.update()

    def _render_intel(self, strat, cands):
        self.solve_body.controls = [self._sugg_row(d, i, top=(i == 0), kind="solve")
                                    for i, d in enumerate(strat[:12])]
        self.shred_body.controls = [self._sugg_row(d, i, top=False, kind="shred")
                                    for i, d in enumerate(cands[:12])]
        self.solve_body.update()
        self.shred_body.update()

    def _hint_status(self):
        vows = sum(1 for x in self.engine.hinted_letters if x in "aeiou")
        cons = len(self.engine.hinted_letters) - vows
        if vows and cons:
            return " — complete"
        if vows and not cons:
            return " — need 1 CONSONANT"
        if cons and not vows:
            return " — need 1 VOWEL"
        return " — need 1 CONSONANT + 1 VOWEL"

    def submit_move(self, e=None):
        if self._busy or self._solved:
            return
        guess = (self.input.value or "").strip().lower()
        if len(guess) != 5 or not guess.isalpha():
            self._toast("Enter a 5-letter word.", ERROR)
            return
        pat = sum(self.colors[i] * (3 ** i) for i in range(5))
        if pat == 0:
            self._toast("Set the result colors (click the tiles).", ERROR)
            return
        ok = self.engine.update_state(guess, pat)
        if not ok:
            self._toast("That pattern is impossible for the current pool.", ERROR)
            return
        self.history.append((guess, list(self.colors)))
        won = self.colors == [2, 2, 2, 2, 2]
        self.colors = [0, 0, 0, 0, 0]
        self.input.value = ""
        self._render_board()
        self.hard_switch.disabled = True
        if won:
            self._solved = True
            self._show_banner(self.engine.turn - 1)
        self._render_board()
        self.page.run_task(self.refresh)

    def _show_banner(self, turns):
        self.banner.visible = True
        self.banner.content = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.CHECK_CIRCLE, color=GREEN, size=18),
                 ft.Text(f"SOLVED in {turns} turn{'s' if turns != 1 else ''}",
                         size=13, weight=ft.FontWeight.BOLD, color=GREEN)],
                spacing=8,
            ),
            bgcolor=PANEL2, border=ft.Border.all(1, GREEN), border_radius=10,
            padding=pad.symmetric(horizontal=12, vertical=8),
        )
        self.banner.update()

    def log_hint(self, e=None):
        letter = (self.hint_entry.value or "").strip().lower()
        if not letter:
            return
        if not self.engine.add_hint(letter):
            self._toast(f"'{letter.upper()}' can't be logged (rule/conflict).", ERROR)
            return
        known = ", ".join(sorted(self.engine.hinted_letters)).upper()
        self.hint_label.value = f"KNOWN: {known}{self._hint_status()}"
        self.hint_entry.value = ""
        self.hint_label.update()
        self.hint_entry.update()
        self.page.run_task(self.refresh)

    def on_hard_toggle(self, e):
        if self.engine.turn > 1:
            return
        self._hard = bool(self.hard_switch.value)
        self._sync_chips()
        self.page.run_task(self.refresh)

    def safe_reset(self, e=None):
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Confirm Reset"),
            content=ft.Text("Wipe all mission data and start a fresh game?"),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self._close_dlg(dlg)),
                ft.TextButton(content=ft.Text("Reset"), on_click=lambda e: (self._close_dlg(dlg), self._finish_reset())),
            ],
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def _finish_reset(self):
        self.engine.reset()
        self.colors = [0, 0, 0, 0, 0]
        self.history = []
        self._solved = False
        self._hard = False
        self.hard_switch.value = False
        self.hard_switch.disabled = False
        self.hint_label.value = ""
        self.input.value = ""
        self.banner.visible = False
        self._render_board()
        self._render_board()
        self._sync_chips()
        self.page.run_task(self.refresh)

    def _close_dlg(self, dlg):
        dlg.open = False
        self.page.update()

    def _toast(self, msg, color=ERROR):
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(msg, color=TEXT), bgcolor=PANEL3,
            duration=2600)
        self.page.snack_bar.open = True
        self.page.update()

    # ── footer ──────────────────────────────────────────────────────
    def _footer(self):
        self.reset_btn = ft.ElevatedButton(
            content=ft.Text("SYSTEM RESET", size=12, weight=ft.FontWeight.BOLD, color=TEXT),
            height=34, bgcolor=PANEL2,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                                 side=ft.BorderSide(1, LINE)),
            on_click=self.safe_reset,
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text("engine: greedy + residual specialist · 2315 answers",
                            size=10, color=FAINT),
                    self.reset_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            bgcolor=PANEL, border=ft.Border(top=ft.BorderSide(1, LINE)),
            padding=pad.symmetric(horizontal=20, vertical=8),
        )


def main(page: ft.Page):
    App(page)


if __name__ == "__main__":
    ft.run(main, view=ft.AppView.FLET)
