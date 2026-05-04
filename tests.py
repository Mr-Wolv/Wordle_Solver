import pandas as pd
import time
import multiprocessing as mp
from Engine import WordleEngine
import random

# --- CONFIGURATION ---
TEST_HARD_MODE = False
SAMPLE_SIZE = 200
NUM_CORES = mp.cpu_count() - 1


def worker_task(word_chunk, log_queue):
    """Processes a chunk and sends live updates to the queue."""
    # Engine loaded once per core for efficiency
    engine = WordleEngine()

    for target in word_chunk:
        target = target.lower().strip()
        engine.reset()
        turns = 0

        while True:
            turns += 1
            strat, _ = engine.get_suggestions(is_hard_mode=TEST_HARD_MODE)

            if not strat:
                log_queue.put((target, -1))  # Signal failure
                break

            guess = strat[0]["word"]
            if guess == target:
                log_queue.put((target, turns))  # Signal success
                break

            pattern = engine.calculate_pattern(guess, target)
            engine.update_state(guess, pattern)

            if turns >= 10:
                log_queue.put((target, 11))  # Signal timeout
                break


def listener_task(log_queue, total_expected):
    count = 0
    results = []
    distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, "fail": 0}
    start_time = time.time()

    while count < total_expected:
        target, turns = log_queue.get()
        count += 1

        # Track Distribution
        if 0 < turns <= 6:
            distribution[turns] += 1
            results.append(turns)
        elif turns > 6:
            distribution[6] += 1  # Any success > 6
            results.append(turns)
        else:
            distribution["fail"] += 1

        # Real-time progress
        if count % 10 == 0 or count == total_expected:
            avg = sum(results) / len(results) if results else 0
            print(
                f"🛰️  [PROFILING: {count:04d}/{total_expected}] | Current Avg: {avg:.3f} | Last: {target.upper()}"
            )

    end_time = time.time()
    total_time = end_time - start_time

    # --- RIGOROUS TEST ANALYSIS REPORT ---
    print("\n" + "═" * 50)
    print(" 💠 BEAST ENGINE: FORENSIC ARCHITECTURE REPORT 💠")
    print("═" * 50)
    print(f"STATUS:         MISSION COMPLETE")
    print(f"THROUGHPUT:     {total_expected / total_time:.2f} words/sec")
    print(f"EFFICIENCY:     {sum(results)/len(results):.4f} Avg Turns")
    print("═" * 50)

    print("📈 SOLUTION DENSITY DISTRIBUTION:")
    for t in range(1, 7):
        label = "SURPASSES PROOF" if t <= 5 else "STRESS DETECTED"
        count_val = distribution[t]
        percent = (count_val / total_expected) * 100
        bar = "█" * int(percent / 2)
        print(f" Turn {t}: {percent:5.1f}% | {bar} ({count_val}) [{label}]")

    if distribution["fail"] > 0:
        print(f" ❌ FAILURES: {distribution['fail']} words collapsed.")

    print("\n🧐 ARCHITECTURAL VERDICT:")
    if max(results) <= 5:
        print(
            " > PROOF VALIDATED: The engine is a TRUE SOLVER. No word exceeded Turn 5."
        )
    else:
        print(
            f" > PROOF ADJUSTED: The engine is an OPTIMIZER. Max turns hit {max(results)}."
        )
    print("═" * 50)


def run_live_stress_test():
    try:
        # 1. Load the full solution set verbatim
        solutions_df = pd.read_csv("valid_solutions.csv")
        all_solutions = solutions_df.iloc[:, 0].dropna().tolist()

        # 2. Textbook Random Sampling
        # This ensures we aren't just testing 'A' words or 'first' words
        if len(all_solutions) > SAMPLE_SIZE:
            print(
                f"🎲 Randomly selecting {SAMPLE_SIZE} targets from pool of {len(all_solutions)}..."
            )
            test_pool = random.sample(all_solutions, SAMPLE_SIZE)
        else:
            print(
                f"⚠️ Sample size exceeds pool. Testing all {len(all_solutions)} words."
            )
            test_pool = all_solutions
            random.shuffle(test_pool)  # Shuffle anyway for non-linear testing

    except Exception as e:
        print(f"Data Error: {e}")
        return

    # Set up Multiprocessing structures[cite: 2, 3]
    manager = mp.Manager()
    log_queue = manager.Queue()

    # 3. Chunk the randomized pool
    chunk_size = len(test_pool) // NUM_CORES
    chunks = [
        test_pool[i : i + chunk_size] for i in range(0, len(test_pool), chunk_size)
    ]

    actual_total = sum(len(c) for c in chunks)

    print(f"🚀 STARTING RANDOMIZED LIVE STRESS TEST ({NUM_CORES} CORES)")
    print(
        f"MODAL ANALYSIS: {'HARD MODE' if TEST_HARD_MODE else 'NORMAL MODE (SOLVER)'}"
    )
    print("-" * 50)

    # Start the listener thread/process for real-time printing
    listener = mp.Process(target=listener_task, args=(log_queue, actual_total))
    listener.start()

    # Start workers
    processes = []
    for chunk in chunks:
        p = mp.Process(target=worker_task, args=(chunk, log_queue))
        p.start()
        processes.append(p)

    # Wait for everything to finish
    for p in processes:
        p.join()
    listener.join()


if __name__ == "__main__":
    run_live_stress_test()
