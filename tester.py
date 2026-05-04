import pandas as pd
import multiprocessing as mp
from Engine import WordleEngine
import random
import argparse
import sys
import time

def worker_task(word_chunk, log_queue, is_hard_mode):
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

def listener_task(log_queue, total_expected, is_hard_mode, silent):
    count = 0
    results = []
    morgue = []
    start_time = time.time()

    while count < total_expected:
        target, turns = log_queue.get()
        count += 1
        results.append(turns)

        if turns > 6 or turns <= 0:
            morgue.append(f"{target.upper()} ({turns} turns)")

        # Use the silent flag to control real-time logging
        if not silent:
            avg_so_far = sum(results) / len(results)
            print(f"[PROFILING: {count:04d}/{total_expected}] | Avg: {avg_so_far:.3f} | Last: {target.upper()}")

    total_duration = time.time() - start_time
    failure_count = len(morgue)
    accuracy = ((total_expected - failure_count) / total_expected) * 100
    avg_turns = sum(results) / len(results) if results else 0

    print("\n" + "═" * 50)
    print(f"PROFILING REPORT: {'HARD' if is_hard_mode else 'NORMAL'} MODE")
    print(f"TEST ACCURACY: {accuracy:.2f}% | AVG TURNS: {avg_turns:.4f}")
    print(f"TOTAL WORDS: {total_expected} | FAILURES: {failure_count}")
    print(f"THROUGHPUT: {total_expected / total_duration:.2f} words/sec")

    if morgue:
        print(f"THE MORGUE: {', '.join(morgue)}")
    print("═" * 50)
    
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Beast Engine Benchmarker")
    parser.add_argument("--mode", choices=["hard", "normal"], default="normal")
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--silent", action="store_true", help="Only show final report")
    args = parser.parse_args()

    # Load data
    try:
        solutions_df = pd.read_csv("valid_solutions.csv")
        all_words = solutions_df.iloc[:, 0].tolist()
        test_pool = random.sample(all_words, min(len(all_words), args.samples))
    except Exception as e:
        print(f"Error loading words: {e}")
        sys.exit(1)

    manager = mp.Manager()
    log_queue = manager.Queue()
    is_hard = args.mode == "hard"

    num_cores = max(1, mp.cpu_count() - 1)
    # Ensure chunking handles small sample sizes correctly
    chunk_size = max(1, len(test_pool) // num_cores)
    chunks = [test_pool[i : i + chunk_size] for i in range(0, len(test_pool), chunk_size)]

    listener = mp.Process(
        target=listener_task, args=(log_queue, len(test_pool), is_hard, args.silent)
    )
    listener.start()

    processes = []
    for chunk in chunks:
        p = mp.Process(target=worker_task, args=(chunk, log_queue, is_hard))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()
    listener.join()