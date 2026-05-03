import customtkinter as ctk
from tkinter import messagebox
from Engine import WordleEngine
import threading  # To prevent UI freezing
import sys
import os

# --- Configuration & Styling ---
COLOR_GREY = "#3a3a3c"
COLOR_YELLOW = "#b59f3b"
COLOR_GREEN = "#538d4e"
COLOR_BG = "#121213"
COLOR_PANEL = "#1e1e1f"
COLOR_TEXT = "#d7dadc"
COLOR_SUBTLE = "#818384"
COLOR_ERROR = "#ff4b4b"


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # type: ignore
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class WordleApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("WORDLE STRAT-CONSOLE // V2.1")
        self.geometry("1150x850")
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=COLOR_BG)

        self.engine = WordleEngine()
        self.colors = [0, 0, 0, 0, 0]
        self.game_active = False  # State lock for Hard Mode

        self.setup_ui()
        self.refresh_suggestions()

    def setup_ui(self):
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT: MISSION LOG ---
        self.left_col = ctk.CTkFrame(self, fg_color="transparent")
        self.left_col.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        self.rules_frame = ctk.CTkFrame(
            self.left_col, fg_color=COLOR_PANEL, corner_radius=12
        )
        self.rules_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(
            self.rules_frame,
            text="OPERATIONAL PROTOCOLS",
            font=("Helvetica", 12, "bold"),
            text_color=COLOR_YELLOW,
        ).pack(pady=8)

        rules_text = (
            "• SHRED: Strategic moves to cull the pool.\n"
            "• SOLVE: High-probability answer candidates.\n"
            "• HARD MODE: Locked once the mission begins."
        )
        ctk.CTkLabel(
            self.rules_frame,
            text=rules_text,
            font=("Helvetica", 11),
            justify="left",
            text_color=COLOR_TEXT,
        ).pack(pady=(0, 10), padx=10)

        self.hist_container = ctk.CTkFrame(
            self.left_col, fg_color=COLOR_PANEL, corner_radius=15
        )
        self.hist_container.pack(expand=True, fill="both")
        ctk.CTkLabel(
            self.hist_container,
            text="MISSION PROGRESSION",
            font=("Helvetica", 14, "bold"),
            text_color=COLOR_SUBTLE,
        ).pack(pady=15)

        self.history_rows = []
        for r in range(6):
            row_f = ctk.CTkFrame(self.hist_container, fg_color="transparent")
            row_f.pack(pady=2)
            cells = []
            for c in range(5):
                cell = ctk.CTkLabel(
                    row_f,
                    text="",
                    width=45,
                    height=45,
                    fg_color="#262627",
                    corner_radius=5,
                    font=("Helvetica", 20, "bold"),
                )
                cell.grid(row=0, column=c, padx=3)
                cells.append(cell)
            self.history_rows.append(cells)

        # --- CENTER: COMMAND INTERFACE ---
        self.center_col = ctk.CTkFrame(self, fg_color="transparent")
        self.center_col.grid(row=0, column=1, padx=10, pady=20, sticky="nsew")

        ctk.CTkLabel(
            self.center_col, text="COMMAND INPUT", font=("Helvetica", 32, "bold")
        ).pack(pady=(20, 40))

        vcmd = (self.register(self.validate_input), "%P")
        self.input_entry = ctk.CTkEntry(
            self.center_col,
            placeholder_text="WORD",
            width=200,
            height=60,
            font=("Helvetica", 32, "bold"),
            justify="center",
            validate="key",
            validatecommand=vcmd,
        )
        self.input_entry.pack(pady=10)

        self.squares_frame = ctk.CTkFrame(self.center_col, fg_color="transparent")
        self.squares_frame.pack(pady=20)
        self.square_btns = []
        for i in range(5):
            btn = ctk.CTkButton(
                self.squares_frame,
                text="",
                width=60,
                height=60,
                fg_color=COLOR_GREY,
                corner_radius=8,
                hover=False,
                command=lambda idx=i: self.toggle_color(idx),
            )
            btn.grid(row=0, column=i, padx=5)
            self.square_btns.append(btn)

        self.hard_mode_var = ctk.BooleanVar(value=False)
        self.hard_mode_switch = ctk.CTkSwitch(
            self.center_col,
            text="ENFORCE HARD MODE",
            variable=self.hard_mode_var,
            command=self.refresh_suggestions,
            progress_color=COLOR_GREEN,
            font=("Helvetica", 12, "bold"),
        )
        self.hard_mode_switch.pack(pady=(0, 25))

        self.submit_btn = ctk.CTkButton(
            self.center_col,
            text="SUBMIT DATA",
            font=("Helvetica", 18, "bold"),
            command=self.submit_move,
            fg_color=COLOR_GREEN,
            height=60,
            hover_color="#3e6b3a",
        )
        self.submit_btn.pack(pady=10, fill="x", padx=40)

        self.reset_btn = ctk.CTkButton(
            self.center_col,
            text="SYSTEM RESET",
            command=self.safe_reset,
            fg_color="#444",
            height=40,
        )
        self.reset_btn.pack(pady=15)

        # --- RIGHT: ANALYTICS ---
        self.right_col = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=15)
        self.right_col.grid(row=0, column=2, padx=20, pady=20, sticky="nsew")

        self.stats_label = ctk.CTkLabel(
            self.right_col,
            text="POOL: 12972 WORDS",
            font=("Helvetica", 16, "bold"),
            text_color=COLOR_GREEN,
        )
        self.stats_label.pack(pady=20)

        self.setup_data_panel("STRATEGIC SUGGESTIONS (SHRED)", COLOR_YELLOW, "strat")
        self.setup_data_panel("ANSWER LIKELIHOOD (SOLVE)", COLOR_GREEN, "cand")

    def setup_data_panel(self, title, color, attr_prefix):
        ctk.CTkLabel(
            self.right_col, text=title, font=("Helvetica", 10, "bold"), text_color=color
        ).pack(pady=(10, 2))
        box = ctk.CTkTextbox(
            self.right_col,
            fg_color=COLOR_BG,
            font=("Courier New", 12),
            text_color=COLOR_TEXT,
        )
        box.pack(padx=15, pady=(0, 15), fill="both", expand=True)
        setattr(self, f"{attr_prefix}_box", box)

    def validate_input(self, P):
        if len(P) > 5:
            return False
        return all(c.isalpha() for c in P) or P == ""

    def toggle_color(self, idx):
        self.colors[idx] = (self.colors[idx] + 1) % 3
        colors_map = {0: COLOR_GREY, 1: COLOR_YELLOW, 2: COLOR_GREEN}
        self.square_btns[idx].configure(fg_color=colors_map[self.colors[idx]])

    def refresh_suggestions(self):
        """Runs suggestion logic in a thread to keep UI snappy."""
        self.config(cursor="watch")  # Set loading cursor
        self.stats_label.configure(
            text="CALCULATING ENTROPY...", text_color=COLOR_YELLOW
        )

        threading.Thread(target=self._threaded_refresh, daemon=True).start()

    def _threaded_refresh(self):
        is_hard = self.hard_mode_var.get()
        strat, cands = self.engine.get_suggestions(is_hard_mode=is_hard)

        # UI updates must happen on the main thread
        self.after(0, lambda: self._update_ui_after_refresh(strat, cands))

    def _update_ui_after_refresh(self, strat, cands):
        pool_size = len(self.engine.possible_indices)
        self.stats_label.configure(
            text=f"POOL: {pool_size} WORDS",
            text_color=COLOR_GREEN if pool_size > 0 else COLOR_ERROR,
        )
        self._update_textbox(self.strat_box, strat, is_strat=True) # type: ignore
        self._update_textbox(self.cand_box, cands, is_strat=False) # type: ignore
        self.config(cursor="")  # Reset cursor

    def _update_textbox(self, box, data, is_strat):
        box.configure(state="normal")
        box.delete("1.0", "end")
        if is_strat:
            box.insert(
                "end", f"{'WORD':<10} | {'SCORE':<7} | {'ROLE'}\n" + "—" * 28 + "\n"
            )
            for item in data:
                role = "SOLVE" if item["is_candidate"] else "SHRED"
                box.insert(
                    "end",
                    f"{item['word'].upper():<10} | {item['score']:>6.2f} | {role}\n",
                )
        else:
            box.insert("end", f"{'WORD':<12} | {'CHANCE'}\n" + "—" * 28 + "\n")
            for item in data:
                box.insert(
                    "end",
                    f"{item['word'].upper():<12} | {(item['win_prob']*100):>5.1f}%\n",
                )
        box.configure(state="disabled")

    def submit_move(self):
        guess = self.input_entry.get().lower().strip()

        if len(guess) != 5:
            messagebox.showwarning(
                "Incomplete Entry", "Word must be exactly 5 letters."
            )
            return
        if guess not in self.engine.all_words:
            messagebox.showerror(
                "Lexicon Error", f"'{guess.upper()}' is not a recognized term."
            )
            return

        pattern_int = sum(p * (3**i) for i, p in enumerate(self.colors))

        success = self.engine.update_state(guess, pattern_int)

        if not success:
            messagebox.showerror(
                "Intelligence Conflict", "Input pattern results in 0 words."
            )
            return

        # LOCK HARD MODE: Game has officially started
        self.game_active = True
        self.hard_mode_switch.configure(state="disabled")

        row = self.engine.turn - 2
        if row < 6:
            colors_map = {0: COLOR_GREY, 1: COLOR_YELLOW, 2: COLOR_GREEN}
            for i, char in enumerate(guess.upper()):
                self.history_rows[row][i].configure(
                    text=char, fg_color=colors_map[self.colors[i]]
                )

        self.input_entry.delete(0, "end")
        self.colors = [0, 0, 0, 0, 0]
        for btn in self.square_btns:
            btn.configure(fg_color=COLOR_GREY)
        self.refresh_suggestions()

    def safe_reset(self):
        if messagebox.askyesno("Confirm Reset", "Wipe all mission data?"):
            self.config(cursor="watch")
            self.stats_label.configure(
                text="SYSTEM REBOOTING...", text_color=COLOR_YELLOW
            )
            self.reset_btn.configure(state="disabled", text="RESETTING...")
            self.after(100, self._finish_reset)

    def _finish_reset(self):
        self.engine.reset()

        # UNLOCK HARD MODE: Reset state
        self.game_active = False
        self.hard_mode_switch.configure(state="normal")

        for row in self.history_rows:
            for cell in row:
                cell.configure(text="", fg_color="#262627")

        self.refresh_suggestions()
        self.reset_btn.configure(state="normal", text="SYSTEM RESET")
        self.config(cursor="")
        messagebox.showinfo("System Reboot", "Engine reset complete.")


if __name__ == "__main__":
    app = WordleApp()
    app.mainloop()
