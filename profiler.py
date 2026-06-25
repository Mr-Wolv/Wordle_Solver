"""
cProfile-based profiler for the Wordle engine.

Runs a single game (against a random secret word), profiles every call,
and prints the top time-consuming functions.

Usage:
    python profiler.py                     # single game, print top 20 lines
    python profiler.py --word HAPPY        # specific secret word
    python profiler.py --mode hard         # hard mode
    python profiler.py --lines 30          # show top 30 lines
    python profiler.py --save results.prof  # save to file for snakeviz
"""

import argparse
import cProfile
import pstats
import io
import random
import sys
from Engine import WordleEngine


def play_game(secret: str, is_hard: bool = False) -> int:
    """Play a single game and return the number of turns taken."""
    engine = WordleEngine()
    turns = 0
    while True:
        turns += 1
        strat, _ = engine.get_suggestions(is_hard_mode=is_hard)
        if not strat:
            return -1
        guess = strat[0]["word"]
        if guess == secret:
            return turns
        pattern = engine.calculate_pattern(guess, secret)
        engine.update_state(guess, pattern)
        if turns >= 10:
            return 11


def main():
    parser = argparse.ArgumentParser(description="Wordle Engine Profiler")
    parser.add_argument(
        "--word",
        type=str,
        default=None,
        help="Secret word to profile (random if not given)",
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "hard"],
        default="normal",
        help="Game mode (default: normal)",
    )
    parser.add_argument(
        "--lines", type=int, default=20, help="Number of top lines to show"
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Save profile data to this file for snakeviz",
    )
    args = parser.parse_args()

    # Pick a secret word
    if args.word:
        secret = args.word.lower().strip()
    else:
        from pandas import read_csv

        df = read_csv("valid_solutions.csv")
        secret = random.choice(df.iloc[:, 0].tolist()).upper()

    is_hard = args.mode == "hard"
    print(f"Profiling: secret='{secret}'  mode={args.mode}")
    print(f"{'-' * 50}")

    profiler = cProfile.Profile()

    # Profile the game function
    profiler.runcall(play_game, secret, is_hard)

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats("cumtime")
    ps.print_stats(args.lines)

    # Also print by internal time
    s2 = io.StringIO()
    ps2 = pstats.Stats(profiler, stream=s2).sort_stats("time")
    ps2.print_stats(args.lines)

    print("=" * 60)
    print("TOP BY CUMULATIVE TIME (total time in function + its callees)")
    print("=" * 60)
    print(s.getvalue())

    print("=" * 60)
    print("TOP BY INTERNAL TIME (time spent in function itself)")
    print("=" * 60)
    print(s2.getvalue())

    if args.save:
        profiler.dump_stats(args.save)
        print(f"Profile saved to {args.save}")
        print(f"View with: snakeviz {args.save}")


if __name__ == "__main__":
    main()
