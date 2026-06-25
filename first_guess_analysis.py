"""
First‑guess analysis: evaluate every word in the dictionary as a starting
guess and rank by the combined entropy + worst‑case score.

Usage:
    python first_guess_analysis.py                    # top 50 listing
    python first_guess_analysis.py --top 20           # top 20 only
    python first_guess_analysis.py --all              # rank all words
    python first_guess_analysis.py --save top100.csv  # export to CSV
"""

import argparse
import numpy as np
import pandas as pd
from Engine import WordleEngine


def main():
    parser = argparse.ArgumentParser(description="First‑guess analyser")
    parser.add_argument("--top", type=int, default=50, help="Number of top words to show")
    parser.add_argument("--all", action="store_true", help="Rank every word (slow)")
    parser.add_argument("--save", type=str, default=None, help="Save results to CSV")
    args = parser.parse_args()

    print("Loading engine ...")
    engine = WordleEngine()
    n = len(engine.all_words)

    # Turn 1: full pool, standard-mode scoring
    pool_indices = engine.possible_indices
    current_weights = engine.global_probs.copy()
    current_weights /= current_weights.sum()

    pool_matrix = engine.matrix[:, pool_indices]

    # Determine how many words to evaluate
    search_range = n if args.all else min(n, 5000)  # 5000 is ~5 seconds

    print(f"Evaluating {search_range:,} starting words ...")
    results = []
    for i in range(search_range):
        patterns = pool_matrix[i]
        counts = np.bincount(patterns, weights=current_weights, minlength=243)
        nz = counts[counts > 0]
        entropy = -float(np.sum(nz * np.log2(nz)))
        win_prob = float(current_weights[i]) if i < len(current_weights) else 0.0
        worst_case = float(counts.max())

        # Standard mode, turn 1 scoring
        score = entropy - 0.3 * worst_case

        results.append({
            "word": engine.all_words[i],
            "entropy": round(entropy, 4),
            "worst_case": round(worst_case, 4),
            "win_prob": round(win_prob, 6),
            "score": round(score, 4),
        })

    # Sort by score descending
    results.sort(key=lambda r: r["score"], reverse=True)

    # Print header
    top_n = args.top if not args.all else min(50, len(results))
    print(f"\n{'=' * 75}")
    print(f"  TOP {top_n} FIRST GUESSES  (standard mode, turn 1)")
    print(f"{'=' * 75}")
    print(f"{'Rank':<5} {'Word':<8} {'Entropy':<10} {'WorstCase':<12} {'WinProb':<10} {'Score':<10}")
    print(f"{'-' * 55}")

    for rank, r in enumerate(results[:top_n], 1):
        print(
            f"{rank:<5} {r['word'].upper():<8} {r['entropy']:<10} "
            f"{r['worst_case']:<12} {r['win_prob']:<10} {r['score']:<10}"
        )

    # Summary stats
    scores = [r["score"] for r in results]
    print(f"\n  Score range: {min(scores):.4f} to {max(scores):.4f}")
    print(f"  Mean score:  {np.mean(scores):.4f}")
    print(f"  Median score:{np.median(scores):.4f}")

    # Top 5 hard-mode first guesses (using hard-mode scoring)
    print(f"\n{'-' * 55}")
    print(f"  TOP 5 HARD MODE FIRST GUESSES  (turn 1, hard scoring)")
    print(f"{'-' * 55}")
    hard_results = []
    for r in results:
        # Hard mode turn 1: entropy - 1.2 * worst_case
        hard_score = r["entropy"] - 1.2 * r["worst_case"]
        hard_results.append({**r, "hard_score": round(hard_score, 4)})
    hard_results.sort(key=lambda r: r["hard_score"], reverse=True)
    print(f"{'Rank':<5} {'Word':<8} {'Entropy':<10} {'WorstCase':<12} {'HardScore':<10}")
    print(f"{'-' * 45}")
    for rank, r in enumerate(hard_results[:5], 1):
        print(
            f"{rank:<5} {r['word'].upper():<8} {r['entropy']:<10} "
            f"{r['worst_case']:<12} {r['hard_score']:<10}"
        )

    if args.save:
        df = pd.DataFrame(results)
        df.to_csv(args.save, index=False)
        print(f"\nSaved {len(results)} results to {args.save}")


if __name__ == "__main__":
    main()
