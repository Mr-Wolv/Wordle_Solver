"""
Shared game helper: play a single Wordle game from start to finish.

Both benchmark.py and analyze_failures.py import ``play_one_game`` from here
instead of defining their own copy.
"""

from Engine import WordleEngine


def play_one_game(target: str, is_hard: bool = False) -> tuple[str, int]:
    """Play a single Wordle game and return (word, turns_taken).

    Creates a fresh ``WordleEngine`` for each call so there is no state leakage
    between games.  The matrix is memory-mapped (``mmap_mode='r'``) so the OS
    shares the physical pages across processes.

    Returns:
        (word, -1)   – engine returned no suggestions (shouldn't happen)
        (word, 1..6) – solved in that many turns
        (word, 11)   – hit the 10-turn safety limit → failure
    """
    engine = WordleEngine()  # __init__ already calls reset()
    target = target.lower().strip()
    turns = 0
    while True:
        turns += 1
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
