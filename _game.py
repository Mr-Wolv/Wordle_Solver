"""
Shared game helper: play a single Wordle game from start to finish.

Both benchmark.py and profiler.py import ``play_one_game`` from here
instead of defining their own copy.

The default ``play_one_game`` lets the solver play optimally with no
external hints (a *ceiling* measurement of the engine itself). Passing
``hints=True`` simulates the NYT "hint" feature: before each turn the
engine is fed the unique letters of the secret that it has not already
been told, mirroring how a human uses the in-game hint button.
"""


from Engine import WordleEngine


def play_one_game(
    target: str,
    is_hard: bool = False,
    hints: bool = False,
) -> tuple[str, int]:
    """Play a single Wordle game and return (word, turns_taken).

    Creates a fresh ``WordleEngine`` for each call so there is no state leakage
    between games.  The matrix is memory-mapped (``mmap_mode='r'``) so the OS
    shares the physical pages across processes.

    Args:
        hints: if True, feed the engine the secret's unique letters as
            external hints (simulates the NYT hint button a human would use).

    Returns:
        (word, -1)   – engine returned no suggestions (shouldn't happen)
        (word, 1..6) – solved in that many turns
        (word, 11)   – hit the 10-turn safety limit → failure
    """
    engine = WordleEngine()  # __init__ already calls reset()
    target = target.lower().strip()
    secret_letters = list(dict.fromkeys(target))  # unique, in order
    told: set[str] = set()
    turns = 0
    while True:
        turns += 1
        if hints:
            # NYT hint button: exactly one consonant AND one vowel, revealed
            # one at a time in order of first appearance.
            want_cons = not any(c in "bcdfghjklmnpqrstvwxyz" for c in told)
            want_vow = not any(c in "aeiou" for c in told)
            for letter in secret_letters:
                if letter in told:
                    continue
                if (letter in "bcdfghjklmnpqrstvwxyz" and want_cons) or (
                    letter in "aeiou" and want_vow
                ):
                    if engine.add_hint(letter):
                        told.add(letter)
                    break  # one hint per turn, in order of appearance
                # ineligible category (already have it) -> keep scanning
        strat, _ = engine.get_suggestions(is_hard_mode=is_hard)
        if not strat:
            return (target, -1)
        guess = strat[0]["word"]
        if guess == target:
            return (target, turns)
        pattern = engine.calculate_pattern(guess, target)
        engine.update_state(guess, pattern)
        if turns >= 10:
            return (target, 11)
