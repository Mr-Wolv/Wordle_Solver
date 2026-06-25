"""
Comprehensive benchmark for the Wordle solver.

Tests the engine on a random sample of solution words in both normal and
hard mode, then prints a detailed report including:

  - Accuracy (% solved within 6 turns)
  - Average turns to solve
  - Turn distribution (how many solved in 1, 2, 3, … turns)
  - Failures (words that took 7+ turns)
  - Throughput (words/sec)

Usage:
    python benchmark.py                         # 200 samples, both modes
    python benchmark.py --samples 500           # 500 samples
    python benchmark.py --mode hard             # hard mode only
    python benchmark.py --mode normal --silent   # normal, silent
    python benchmark.py --json                  # machine-readable JSON output
"""

import argparse
import json
import multiprocessing as mp
import random
import sys
import time

import pandas as pd
from Engine import WordleEngine


def worker_task(word_chunk, log_queue, is_hard_mode):
    """Worker process: play games for a chunk of words and report results."""
    engine = WordleEngine()
    for target in word_chunk:
        target = target.lower().strip()
        engine.reset()
        turns = 0
        while True:
            turns += 1
            strat, _ = engine.get_suggestions(is_hard_mode=is_hard_mode)
            if not strat:
                log_queue.put((target, -1))
                break
            guess = strat[0]["word"]
            if guess == target:
                log_queue.put((target, turns))
                break
            pattern = engine.calculate_pattern(guess, target)
            engine.update_state(guess, pattern)
            if turns >= 10:
                log_queue.put((target, 11))
                break


def drain_queue(log_queue, total_expected, silent):
    """Drain the result queue from worker processes."""
    results = []
    morgue = []
    count = 0
    while count < total_expected:
        target, turns = log_queue.get()
        count += 1
        results.append(turns)
        if turns > 6 or turns <= 0:
            morgue.append(f"{target.upper()} ({turns} turns)")
        if not silent:
            avg_so_far = sum(results) / len(results)
            print(
                f"[{count:04d}/{total_expected}] | Avg: {avg_so_far:.3f} | "
                f"Last: {target.upper()} ({turns} turn{'s' if turns != 1 else ''})"
            )
    return results, morgue

def run_benchmark(
    samples: int,
    is_hard: bool,
    silent: bool,
    seed: int | None = None,
) -> dict:
    """Run the benchmark and return a stats dict."""
    # Load solution words
    try:
        solutions_df = pd.read_csv("valid_solutions.csv")
        all_words = solutions_df.iloc[:, 0].tolist()
    except Exception as e:
        print(f"Error loading words: {e}")
        sys.exit(1)

    if seed is not None:
        random.seed(seed)
    test_pool = random.sample(all_words, min(len(all_words), samples))

    manager = mp.Manager()
    log_queue = manager.Queue()

    num_cores = max(1, mp.cpu_count() - 1)
    chunk_size = max(1, len(test_pool) // num_cores)
    chunks = [
        test_pool[i : i + chunk_size] for i in range(0, len(test_pool), chunk_size)
    ]

    processes = []
    for chunk in chunks:
        p = mp.Process(target=worker_task, args=(chunk, log_queue, is_hard))
        p.start()
        processes.append(p)

    # Drain the queue while workers are still running
    start_time = time.time()
    results, morgue = drain_queue(log_queue, len(test_pool), silent)
    total_duration = time.time() - start_time

    for p in processes:
        p.join()

    failure_count = len(morgue)
    accuracy = ((len(test_pool) - failure_count) / len(test_pool)) * 100
    avg_turns = sum(results) / len(results) if results else 0

    # Turn distribution
    dist = {}
    for t in range(1, 11):
        n = results.count(t)
        if n > 0:
            dist[t] = n
    fail_n = results.count(11)
    if fail_n:
        dist["7+ (fail)"] = fail_n

    return {
        "mode": "HARD" if is_hard else "NORMAL",
        "samples": len(test_pool),
        "accuracy": round(accuracy, 2),
        "avg_turns": round(avg_turns, 4),
        "failures": failure_count,
        "throughput": round(len(test_pool) / total_duration, 2),
        "turn_distribution": dist,
        "morgue": morgue,
        "duration_seconds": round(total_duration, 1),
    }


def print_report(stats: dict):
    """Print a formatted benchmark report."""
    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  WORDLE SOLVER BENCHMARK  —  {stats['mode']} MODE")
    print(f"{sep}")
    print(f"  Accuracy:       {stats['accuracy']:.2f}%  "
          f"({stats['samples'] - stats['failures']}/{stats['samples']})")
    print(f"  Avg turns:      {stats['avg_turns']:.4f}")
    print(f"  Failures:       {stats['failures']}")
    print(f"  Throughput:     {stats['throughput']} words/sec")
    print(f"  Duration:       {stats['duration_seconds']}s")

    dist = stats["turn_distribution"]
    if dist:
        print(f"\n  Turn Distribution:")
        max_n = max(dist.values())
        for t in sorted(dist.keys(), key=lambda k: str(k)):
            n = dist[t]
            bar = "#" * max(1, int(n / max_n * 30))
            pct = n / stats["samples"] * 100
            print(f"    {str(t):>10}: {bar} {n:>4} ({pct:>5.1f}%)")

    if stats["morgue"]:
        print(f"\n  THE MORGUE:")
        for w in stats["morgue"]:
            print(f"    {w}")
    print(f"{sep}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Wordle Solver Benchmark"
    )
    parser.add_argument(
        "--samples", type=int, default=200, help="Number of words to test"
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "hard", "both"],
        default="both",
        help="Game mode (default: both)",
    )
    parser.add_argument(
        "--silent", action="store_true", help="Suppress real-time logging"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON (machine-readable)"
    )
    args = parser.parse_args()

    modes = []
    if args.mode in ("normal", "both"):
        modes.append(False)
    if args.mode in ("hard", "both"):
        modes.append(True)

    all_stats = []
    for is_hard in modes:
        stats = run_benchmark(
            samples=args.samples,
            is_hard=is_hard,
            silent=args.silent,
            seed=args.seed,
        )
        all_stats.append(stats)
        if not args.json:
            print_report(stats)

    if args.json:
        print(json.dumps(all_stats, indent=2))


if __name__ == "__main__":
    # Need freeze_support for multiprocessing on Windows
    mp.freeze_support()
    main()
