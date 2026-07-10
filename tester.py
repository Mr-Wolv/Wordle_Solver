"""
Legacy tester — kept for backwards compatibility.

Prefer the newer tools:
    python benchmark.py           # comprehensive benchmark
    python profiler.py            # cProfile hot-spot analysis

Usage:
    python tester.py                          # 50 samples, normal, sequential
    python tester.py --mode hard --samples 200
    python tester.py --silent
"""

import argparse
import random
import sys
import time

import pandas as pd
from _game import play_one_game


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Legacy Wordle Tester")
    parser.add_argument("--mode", choices=["hard", "normal"], default="normal")
    parser.add_argument("--samples", type=int, default=50, help="Words to test (default: 50, was 200)")
    parser.add_argument("--silent", action="store_true", help="Only show final report")
    args = parser.parse_args()

    try:
        solutions_df = pd.read_csv("valid_solutions.csv")
        all_words = solutions_df.iloc[:, 0].tolist()
    except Exception as e:
        print(f"Error loading words: {e}")
        sys.exit(1)

    test_pool = random.sample(all_words, min(len(all_words), args.samples))
    is_hard = args.mode == "hard"

    results = []
    morgue = []
    start_time = time.time()

    for idx, word in enumerate(test_pool):
        _, turns = play_one_game(word, is_hard)
        results.append(turns)
        if turns > 6 or turns <= 0:
            morgue.append(f"{word.upper()} ({turns} turns)")
        if not args.silent and (idx + 1) % max(1, len(test_pool) // 20) == 0:
            avg = sum(results) / len(results)
            print(f"[{idx+1:04d}/{len(test_pool)}] | Avg: {avg:.3f}")

    total_duration = time.time() - start_time
    failure_count = len(morgue)
    accuracy = ((len(test_pool) - failure_count) / len(test_pool)) * 100
    avg_turns = sum(results) / len(results) if results else 0

    sep = "=" * 50
    print(f"\n{sep}")
    print(f"TEST REPORT: {'HARD' if is_hard else 'NORMAL'} MODE")
    print(f"ACCURACY: {accuracy:.2f}% | AVG TURNS: {avg_turns:.4f}")
    print(f"WORDS: {len(test_pool)} | FAILURES: {failure_count}")
    print(f"THROUGHPUT: {len(test_pool) / total_duration:.2f} words/sec")
    if morgue:
        print(f"MORGUE: {', '.join(morgue)}")
    print(sep)
