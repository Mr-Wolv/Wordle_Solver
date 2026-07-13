import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from wordle_solver.utils import data_path
from wordle_solver.engine import WordleEngine

SOL = pd.read_csv(data_path("valid_solutions.csv"))["word"].tolist()
# h-family: all solution words containing 'h' (these are the only words that
# can ever be hinted with 'h' as their first-revealed consonant).
H = [w for w in SOL if "h" in w]
print(f"h-family size: {len(H)}", flush=True)

CONS = set("bcdfghjklmnpqrstvwxyz"); VOW = set("aeiou")

def solve_with_first(g_idx, secret, mode=True):
    """Play the game forcing guess `g_idx` at turn 1, greedy+specialist after."""
    e = WordleEngine(); e.reset()
    secL = list(dict.fromkeys(secret))
    told = set()
    turns = 0
    while True:
        turns += 1
        wc = not any(c in CONS for c in told)
        wv = not any(c in VOW for c in told)
        for L in secL:
            if L in told:
                continue
            if (L in CONS and wc) or (L in VOW and wv):
                if e.add_hint(L):
                    told.add(L)
                break
        if turns == 1:
            g = SOL[g_idx]
        else:
            s, _ = e.get_suggestions(is_hard_mode=mode)
            if not s:
                return -1
            g = s[0]["word"]
        if g == secret:
            return turns
        if turns >= 7:
            return -1
        e.update_state(g, e.calculate_pattern(g, secret))

if __name__ == "__main__":
    # candidate first guesses: all solution words (good spreaders); rank by avg turns
    cands = list(range(len(SOL)))
    best = None
    t0 = time.time()
    for ci, g_idx in enumerate(cands):
        if ci % 200 == 0:
            print(f"  candidate {ci}/{len(cands)} elapsed {time.time()-t0:.0f}s best={best}", flush=True)
        ok = True
        tot = 0
        for sec in H:
            t = solve_with_first(g_idx, sec)
            if t < 0:
                ok = False
                break
            tot += t
        if ok:
            avg = tot / len(H)
            if best is None or avg < best[1]:
                best = (SOL[g_idx], avg)
                print(f"  FAMILY-SAFE g='{SOL[g_idx]}' avg={avg:.3f}", flush=True)

    print("RESULT best:", best, flush=True)
    if best:
        import json
        with open(data_path("t1_h_opening.json"), "w") as f:
            # store word + its solution index
            json.dump({"h": SOL.index(best[0])}, f)
        print("written t1_h_opening.json", flush=True)
    else:
        print("NO family-safe h opening found among solution words", flush=True)
