import customtkinter as ctk
from Engine import WordleEngine

# Color Palette
COLOR_GREY = "#3a3a3c"
COLOR_YELLOW = "#b59f3b"
COLOR_GREEN = "#538d4e"
COLOR_BG = "#121213"
COLOR_PANEL = "#1e1e1f"
COLOR_TEXT = "#d7dadc"
COLOR_SUBTLE = "#818384"


class WordleApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("WORDLE STRAT-CONSOLE")

        # Automatic platform scaling
        self.geometry("1150x850")
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=COLOR_BG)

        self.engine = WordleEngine()
        self.colors = [0, 0, 0, 0, 0]

        self.setup_ui()
        self.refresh_suggestions()

    def setup_ui(self):
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT: PROGRESSION & RULES ---
        self.left_col = ctk.CTkFrame(self, fg_color="transparent")
        self.left_col.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        # Rules Panel (The "Usage" fix)
        self.rules_frame = ctk.CTkFrame(
            self.left_col, fg_color=COLOR_PANEL, corner_radius=12
        )
        self.rules_frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(
            self.rules_frame,
            text="OPERATIONAL RULES",
            font=("Helvetica", 12, "bold"),
            text_color=COLOR_YELLOW,
        ).pack(pady=8)

        rules_text = (
            "• SHRED: High-entropy words to narrow the pool.\n"
            "• SOLVE: Actual candidates for the final answer.\n"
            "• INPUT: Type word, click boxes for colors.\n"
            "• SUBMIT: Updates engine & progression log."
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

        # --- CENTER: CONTROL ---
        self.center_col = ctk.CTkFrame(self, fg_color="transparent")
        self.center_col.grid(row=0, column=1, padx=10, pady=20, sticky="nsew")

        ctk.CTkLabel(
            self.center_col, text="COMMAND INPUT", font=("Helvetica", 32, "bold")
        ).pack(pady=(20, 40))

        self.input_entry = ctk.CTkEntry(
            self.center_col,
            placeholder_text="WORD",
            width=200,
            height=60,
            font=("Helvetica", 32, "bold"),
            justify="center",
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

        self.submit_btn = ctk.CTkButton(
            self.center_col,
            text="SUBMIT DATA",
            font=("Helvetica", 18, "bold"),
            command=self.submit_move,
            fg_color=COLOR_GREEN,
            height=60,
        )
        self.submit_btn.pack(pady=20, fill="x", padx=40)

        self.reset_btn = ctk.CTkButton(
            self.center_col,
            text="SYSTEM RESET",
            command=self.safe_reset,
            fg_color="#444",
            height=40,
        )
        self.reset_btn.pack(pady=5)

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

        self.setup_data_panel("STRATEGIC SUGGESTIONS", COLOR_YELLOW, "strat")
        self.setup_data_panel("ANSWER LIKELIHOOD", COLOR_GREEN, "cand")

    def setup_data_panel(self, title, color, attr_prefix):
        ctk.CTkLabel(
            self.right_col, text=title, font=("Helvetica", 12, "bold"), text_color=color
        ).pack(pady=(10, 2))
        box = ctk.CTkTextbox(
            self.right_col,
            fg_color=COLOR_BG,
            font=("Courier New", 13),
            text_color=COLOR_TEXT,
        )
        box.pack(padx=15, pady=(0, 15), fill="both", expand=True)
        setattr(self, f"{attr_prefix}_box", box)

    def toggle_color(self, idx):
        self.colors[idx] = (self.colors[idx] + 1) % 3
        colors_map = {0: COLOR_GREY, 1: COLOR_YELLOW, 2: COLOR_GREEN}
        self.square_btns[idx].configure(fg_color=colors_map[self.colors[idx]])

    def refresh_suggestions(self):
        strat, cands = self.engine.get_suggestions()
        self.stats_label.configure(
            text=f"POOL: {len(self.engine.possible_indices)} WORDS"
        )

        self.strat_box.delete("1.0", "end") # type: ignore
        self.strat_box.insert( # type: ignore
            "end", f"{'WORD':<10} | {'SCORE':<7} | {'ROLE'}\n" + "—" * 28 + "\n"
        )
        for item in strat:
            role = "SOLVE" if item["is_candidate"] else "SHRED"
            self.strat_box.insert( # type: ignore
                "end", f"{item['word'].upper():<10} | {item['score']:>6.2f} | {role}\n"
            )

        self.cand_box.delete("1.0", "end") # type: ignore
        self.cand_box.insert("end", f"{'WORD':<12} | {'CHANCE'}\n" + "—" * 28 + "\n") # type: ignore
        for item in cands:
            self.cand_box.insert( # type: ignore
                "end", f"{item['word'].upper():<12} | {(item['win_prob']*100):>5.1f}%\n"
            )

    def submit_move(self):
        guess = self.input_entry.get().lower().strip()
        if len(guess) != 5 or guess not in self.engine.all_words:
            return

        pattern_int = sum(p * (3**i) for i, p in enumerate(self.colors))
        row = self.engine.turn - 1
        if row < 6:
            colors_map = {0: COLOR_GREY, 1: COLOR_YELLOW, 2: COLOR_GREEN}
            for i, char in enumerate(guess.upper()):
                self.history_rows[row][i].configure(
                    text=char, fg_color=colors_map[self.colors[i]]
                )

        self.engine.update_state(guess, pattern_int)
        self.input_entry.delete(0, "end")
        self.colors = [0, 0, 0, 0, 0]
        for btn in self.square_btns:
            btn.configure(fg_color=COLOR_GREY)
        self.refresh_suggestions()

    def safe_reset(self):
        self.stats_label.configure(text="SYSTEM REBOOTING...", text_color=COLOR_YELLOW)
        self.reset_btn.configure(state="disabled", text="RESETTING...")
        self.after(100, self._finish_reset)

    def _finish_reset(self):
        self.engine.reset()
        for row in self.history_rows:
            for cell in row:
                cell.configure(text="", fg_color="#262627")
        self.refresh_suggestions()
        self.reset_btn.configure(state="normal", text="SYSTEM RESET")


if __name__ == "__main__":
    app = WordleApp()
    app.mainloop()
