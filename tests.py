import pandas as pd
import time
import random
from Engine import WordleEngine


def run_random_stress_test(csv_path="valid_solutions.csv", sample_size=200):
    try:
        # Load the textbook solutions
        solutions_df = pd.read_csv(csv_path)
        # Convert the first column to a list of words
        all_solutions = solutions_df.iloc[:, 0].dropna().tolist()

        # Textbook Random Sampling
        if len(all_solutions) > sample_size:
            test_subset = random.sample(all_solutions, sample_size)
        else:
            test_subset = all_solutions
            sample_size = len(all_solutions)

    except Exception as e:
        print(f"❌ ERROR: Could not load {csv_path}. {e}")
        return

    print(f"🔥 STARTING RANDOM STRESS TEST")
    print(f"Sample Size: {sample_size} words | Mode: Hard Mode ON")
    print("-" * 60)

    results = []
    failures = []
    start_time = time.time()

    for idx, secret_word in enumerate(test_subset, 1):
        target = secret_word.lower().strip()
        engine = WordleEngine()
        turns = 0

        while True:
            turns += 1
            # 1. Get suggestions (Testing your merged Hard Mode logic)
            strat, _ = engine.get_suggestions(is_hard_mode=True)

            if not strat:
                print(
                    f"[{idx:03d}/{sample_size}] ❌ {target.upper():<7} | ERROR: Engine collapsed."
                )
                failures.append((target, "Zero-Pool Collapse"))
                break

            guess = strat[0]["word"]
            pattern = engine.calculate_pattern(guess, target)

            # 2. Update engine state (The "Fool-Proof" check)
            success = engine.update_state(guess, pattern)

            if not success:
                print(
                    f"[{idx:03d}/{sample_size}] ❌ {target.upper():<7} | ERROR: Impossible Pattern at Turn {turns}"
                )
                failures.append((target, f"Update failed at turn {turns}"))
                break

            # 3. Check for Win
            if guess == target:
                results.append(turns)
                avg = sum(results) / len(results)
                # Print real-time success line
                print(
                    f"[{idx:03d}/{sample_size}] ✅ {target.upper():<7} | Turns: {turns:<2} | Avg: {avg:.3f}"
                )
                break

            # Safety break for infinite loops
            if turns > 10:
                print(
                    f"[{idx:03d}/{sample_size}] ⚠️ {target.upper():<7} | TIMEOUT: 10+ turns."
                )
                failures.append((target, "Turn limit exceeded"))
                break

    end_time = time.time()

    # --- FINAL TEXTBOOK REPORT ---
    print("\n" + "=" * 40)
    print("      STRESS TEST SUMMARY")
    print("=" * 40)
    print(f"Words Tested:     {sample_size}")
    print(f"Success Rate:     {((len(results)/sample_size)*100):.1f}%")
    if results:
        print(f"Average Turns:    {sum(results)/len(results):.3f}")
        print(f"Max Turns:        {max(results)}")
    print(f"Total Time:       {end_time - start_time:.2f}s")

    if failures:
        print("\n🚩 PATHOLOGICAL CASES FOUND:")
        for word, reason in failures:
            print(f" - {word.upper()}: {reason}")
    else:
        print("\n✨ NO ERRORS FOUND. Engine state logic is stable.")


if __name__ == "__main__":
    # You can change the 200 here if you want a different "snack-sized" test
    run_random_stress_test(sample_size=200)
