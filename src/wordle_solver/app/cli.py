"""
Interactive CLI Wordle Solver.

Lets you play Wordle in the terminal with AI-powered suggestions.
Enter your guess and the colour pattern, and the engine tells you
the best next moves.

Usage:
    python cli.py                               # interactive mode
    python cli.py --guess CRANE --pattern 02222  # single-shot mode
    python cli.py --hard                         # hard mode

Pattern format: 5-character string of 0 (grey), 1 (yellow), 2 (green).
Example: --pattern 02220 means:
    letter 1: grey (0)
    letter 2: green (2)
    letter 3: green (2)
    letter 4: green (2)
    letter 5: grey (0)
"""

import argparse
import sys
from wordle_solver.engine import WordleEngine
from wordle_solver.engine.modes import MODE_REGISTRY


def parse_pattern(pattern_str: str) -> int:
    """Convert a 5-char pattern string like '02220' to a base-3 integer."""
    if len(pattern_str) != 5:
        raise ValueError("Pattern must be exactly 5 characters (e.g. '02220')")
    p = []
    for ch in pattern_str:
        d = int(ch)
        if d not in (0, 1, 2):
            raise ValueError(f"Invalid pattern digit '{ch}' -- use 0, 1, or 2")
        p.append(d)
    # Encode as base-3 integer
    return sum(p[i] * (3**i) for i in range(5))


def show_suggestions(engine, is_hard: bool):
    """Print the current suggestions."""
    strat, cands = engine.get_suggestions(is_hard_mode=is_hard)
    pool_size = len(engine.possible_indices)

    print(f"\n  Pool: {pool_size} possible word{'s' if pool_size != 1 else ''}  |  "
          f"Turn: {engine.turn}")
    print(f"  {'-' * 50}")

    print(f"  STRATEGIC SUGGESTIONS (best info-gain):")
    print(f"  {'Word':<12} {'Score':<8} {'Role':<8}")
    for item in strat[:5]:
        role = "SOLVE" if item["is_candidate"] else "SHRED"
        print(f"  {item['word'].upper():<12} {item['score']:<8.2f} {role:<8}")

    print(f"\n  ANSWER LIKELIHOOD (top candidates):")
    print(f"  {'Word':<12} {'Chance':<8}")
    for item in cands[:5]:
        print(f"  {item['word'].upper():<12} {item['win_prob'] * 100:<8.2f}%")

    if strat:
        best = strat[0]
        print(f"\n  >> Best suggestion: {best['word'].upper()} "
              f"(score={best['score']:.2f})")


def interactive_mode(is_hard: bool):
    """Run the interactive solver."""
    engine = WordleEngine()
    engine.set_mode("hard_0" if is_hard else "normal_0")  # lock the domain
    print(f"{'=' * 55}")
    print(f"  WORDLE SOLVER  --  {'HARD' if is_hard else 'NORMAL'} MODE")
    print(f"  Enter your guesses and colour patterns interactively.")
    print(f"{'=' * 55}")

    show_suggestions(engine, is_hard)

    while True:
        engine.reset()
        print(f"\n{'-' * 55}")
        print(f"  NEW GAME")
        print(f"{'-' * 55}")
        show_suggestions(engine, is_hard)

        while True:
            pool_size = len(engine.possible_indices)
            if pool_size <= 1:
                if pool_size == 1:
                    answer = engine.all_words[engine.possible_indices[0]]
                    print(f"\n  >> ANSWER: {answer.upper()}!")
                break

            guess = input(f"\n  Enter your guess (or /reset, /quit, /hint <letter>): ").strip().lower()
            if guess == "/quit":
                print("  Goodbye!")
                return
            if guess == "/reset":
                break

            if guess.startswith("/hint"):
                parts = guess.split()
                if len(parts) != 2 or len(parts[1]) != 1 or not parts[1].isalpha():
                    print("  Usage: /hint <letter>   (e.g. /hint e)")
                    continue
                ok = engine.add_hint(parts[1])
                if not ok:
                    print(f"  Hint '{parts[1].upper()}' contradicts the current pool — ignored.")
                    continue
                print(f"  Hint registered: answer contains '{parts[1].upper()}'.")
                show_suggestions(engine, is_hard)
                continue

            if len(guess) != 5 or not guess.isalpha():
                print("  Invalid guess — must be 5 letters.")
                continue

            if guess not in engine.all_words:
                print(f"  '{guess.upper()}' is not in the word list.")
                continue

            pattern_str = input(
                f"  Enter pattern for {guess.upper()} "
                f"(e.g. 02220): "
            ).strip()

            try:
                pattern_int = parse_pattern(pattern_str)
            except ValueError as e:
                print(f"  {e}")
                continue

            success = engine.update_state(guess, pattern_int)
            if not success:
                print("  ERROR: No words match this pattern.")
                continue

            show_suggestions(engine, is_hard)


def single_shot(guess: str, pattern_str: str, is_hard: bool):
    """Run a single turn and show suggestions."""
    engine = WordleEngine()
    engine.set_mode("hard_0" if is_hard else "normal_0")  # lock the domain
    pattern_int = parse_pattern(pattern_str)

    if guess not in engine.all_words:
        print(f"'{guess.upper()}' is not in the word list.")
        sys.exit(1)

    success = engine.update_state(guess, pattern_int)
    if not success:
        print("ERROR: No words match this pattern.")
        sys.exit(1)

    show_suggestions(engine, is_hard)


def main():
    parser = argparse.ArgumentParser(description="Wordle Solver CLI")
    parser.add_argument("--guess", type=str, help="Single-shot guess word")
    parser.add_argument("--pattern", type=str, help="Single-shot pattern (e.g. 02220)")
    parser.add_argument("--hard", action="store_true", help="Hard mode")
    args = parser.parse_args()

    is_hard = args.hard

    if args.guess or args.pattern:
        if not args.guess or not args.pattern:
            print("Both --guess and --pattern are required for single-shot mode")
            sys.exit(1)
        single_shot(args.guess, args.pattern, is_hard)
    else:
        try:
            interactive_mode(is_hard)
        except KeyboardInterrupt:
            print("\n  Goodbye!")


if __name__ == "__main__":
    main()
