"""
Exhaustive edge-case analysis: simulate every possible solution word in both
modes and report the worst-performing words.

Usage:
    python analyze_failures.py                      # normal mode only
    python analyze_failures.py --mode hard          # hard mode only
    python analyze_failures.py --mode both          # both modes
    python analyze_failures.py --save results.csv   # export full results
"""

import argparse
import multiprocessing as mp
import time
import sys

import pandas as pd
from Engine import WordleEngine



def worker(words_chunk, log_queue, is_hard):
    engine = WordleEngine()
    for word in words_chunk:
        word = word.lower().strip()
        engine.reset()
        turns = 0
        while True:
            turns += 1
            strat, _ = engine.get_suggestions(is_hard_mode=is_hard)
            if not strat:
                log_queue.put((word, -1))
                break
            guess = strat[0]["word"]
            if guess == word:
                log_queue.put((word, turns))
                break
            pattern = engine.calculate_pattern(guess, word)
            engine.update_state(guess, pattern)
            if turns >= 10:
                log_queue.put((word, 11))
                break


def run_analysis(solutions, is_hard, silent):
    """Test all words and return (results_list, morgue_list)."""
    manager = mp.Manager()
    q = manager.Queue()

    # Chunk by CPU count
    n_workers = max(1, mp.cpu_count() - 1)
    chunk_size = max(1, len(solutions) // n_workers)
    chunks = [solutions[i:i + chunk_size] for i in range(0, len(solutions), chunk_size)]

    procs = []
    for c in chunks:
        p = mp.Process(target=worker, args=(c, q, is_hard))
        p.start()
        procs.append(p)

    results = []
    morgue = []
    count = 0
    total = len(solutions)
    while count < total:
        word, turns = q.get()
        count += 1
        results.append((word, turns))
        if turns > 6 or turns <= 0:
            morgue.append((word, turns))
        if not silent and count % 200 == 0:
            print(f"  [{count}/{total}] processed ...")

    for p in procs:
        p.join()

    return results, morgue


def print_report(results, morgue, duration, mode_label):
    total = len(results)
    failures = len(morgue)
    acc = (total - failures) / total * 100
    turns_list = [t for _, t in results]
    avg = sum(turns_list) / total

    # Turn distribution
    dist = {}
    for t in range(1, 11):
        n = turns_list.count(t)
        if n:
            dist[t] = n
    fail_n = turns_list.count(11)
    if fail_n:
        dist["7+ (fail)"] = fail_n

    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  EXHAUSTIVE ANALYSIS  —  {mode_label}")
    print(f"{sep}")
    print(f"  Words tested:  {total}")
    print(f"  Accuracy:      {acc:.4f}%  ({total - failures}/{total})")
    print(f"  Avg turns:     {avg:.4f}")
    print(f"  Failures:      {failures}")
    print(f"  Duration:      {duration:.1f}s")
    print(f"  Throughput:    {total / duration:.2f} words/sec")

    if dist:
        print(f"\n  Turn Distribution:")
        max_n = max(dist.values())
        for k in sorted(dist.keys(), key=str):
            n = dist[k]
            bar = "#" * max(1, int(n / max_n * 30))
            print(f"    {str(k):>10}: {bar} {n:>4} ({n/total*100:>5.2f}%)")

    # Bottom 20 worst words
    if morgue:
        morgue.sort(key=lambda x: -x[1])
        print(f"\n  THE MORGUE ({len(morgue)} words):")
        for word, turns in morgue[:20]:
            print(f"    {word.upper():<10} ({turns} turns)")
    else:
        print(f"\n  THE MORGUE: empty — no failures!")

    # Also show the hardest-to-solve words (even within 6)
    sorted_all = sorted(results, key=lambda x: -x[1])[:10]
    print(f"\n  Hardest words (most turns):")
    for word, turns in sorted_all:
        status = "FAIL" if turns > 6 else f"OK ({turns})"
        print(f"    {word.upper():<10} {turns} turn{'s' if turns != 1 else ''}  [{status}]")

    print(sep)


def main():
    parser = argparse.ArgumentParser(description="Exhaustive edge-case analyser")
    parser.add_argument("--mode", choices=["normal", "hard", "both"], default="both")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--save", type=str, default=None, help="Save results to CSV")
    args = parser.parse_args()

    solutions = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()
    print(f"Loaded {len(solutions)} solution words")

    modes = [(False, "NORMAL MODE")]
    if args.mode in ("hard", "both"):
        modes.append((True, "HARD MODE"))
    if args.mode == "hard":
        modes = [(True, "HARD MODE")]

    all_stats = []
    for is_hard, label in modes:
        print(f"\n{'#' * 60}")
        print(f"  {label}")
        print(f"{'#' * 60}")
        t0 = time.time()
        results, morgue = run_analysis(solutions, is_hard, args.silent)
        dur = time.time() - t0
        print_report(results, morgue, dur, label)
        all_stats.append((label, results, morgue))

    # Combined CSV export
    if args.save:
        rows = []
        for label, results, _ in all_stats:
            for word, turns in results:
                rows.append({"word": word, "turns": turns, "mode": label})
        pd.DataFrame(rows).to_csv(args.save, index=False)
        print(f"\nResults saved to {args.save}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
