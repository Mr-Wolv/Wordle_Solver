"""
Unit tests for the WordleEngine core methods.

Run with: pytest test_engine.py -v
"""

import pytest
import numpy as np
import pandas as pd
from wordle_solver.engine import WordleEngine

# Real NYT answer universe (what the solver actually targets).
VALID_SOLUTIONS: list[str] = pd.read_csv("valid_solutions.csv").iloc[:, 0].tolist()


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    """Create a single engine instance for all tests (matrix load is expensive)."""
    return WordleEngine()


# ── Initialisation ───────────────────────────────────────────────

class TestInit:
    def test_all_words_loaded(self, engine):
        assert len(engine.all_words) > 0
        assert all(isinstance(w, str) for w in engine.all_words)

    def test_word_to_idx_o1_lookup(self, engine):
        """Verify the O(1) dict lookup and that all words have entries."""
        assert len(engine.word_to_idx) == len(engine.all_words)
        for idx, word in enumerate(engine.all_words):
            assert engine.word_to_idx[word] == idx

    def test_global_probs_normalised(self, engine):
        """Global probabilities should sum to 1."""
        assert abs(engine.global_probs.sum() - 1.0) < 1e-6

    def test_possible_indices_full_at_start(self, engine):
        """Fresh engine: pool starts full (all valid answers)."""
        assert len(engine.possible_indices) == len(engine.lex.solution_words)
        assert engine.possible_mask.all()

    def test_turn_one_at_start(self, engine):
        assert engine.turn == 1


# ── calculate_pattern ─────────────────────────────────────────────

class TestCalculatePattern:
    def test_all_green(self, engine):
        """Same word → all greens (pattern 242)."""
        p = engine.calculate_pattern("crane", "crane")
        # 2 + 2*3 + 2*9 + 2*27 + 2*81 = 242
        assert p == 242

    def test_all_grey(self, engine):
        """No letters in common → all grey (pattern 0)."""
        p = engine.calculate_pattern("abcde", "fghij")
        assert p == 0

    def test_one_yellow(self, engine):
        """Letter exists but wrong position."""
        p = engine.calculate_pattern("abcde", "fghda")
        # 'a' yellow at pos0 (1), 'd' green at pos3 (2)
        # pattern = 1,0,0,2,0 → 1*1 + 2*27 = 55
        assert p == 55

    def test_one_green(self, engine):
        """Exact match at one position."""
        p = engine.calculate_pattern("abcde", "afghi")
        # 'a' green at pos0 (2) → 2 * 3^0 = 2
        assert p == 2

    def test_mixed_pattern(self, engine):
        """A typical Wordle pattern."""
        # Guess: CRANE, Secret: CRONY
        p = engine.calculate_pattern("crane", "crony")
        expected = 2 + 2*3 + 2*27  # 2 + 6 + 54 = 62
        assert p == expected

    def test_double_letter_partial(self, engine):
        """If guess has two 'a's but secret has one, only one scores."""
        p = engine.calculate_pattern("aaaaa", "bcdea")
        # One 'a' at pos4 is green → 2 * 81 = 162
        assert p == 2 * 81

    def test_double_letter_exact(self, engine):
        """If both have two 'a's, both score."""
        p = engine.calculate_pattern("ababa", "abaca")
        expected = 2 + 2*3 + 2*9 + 2*81  # 2 + 6 + 18 + 162 = 188
        assert p == expected


# ── update_state & reset ────────────────────────────────────────

class TestUpdateState:
    def test_simple_filter(self, engine):
        """After guessing 'crane' with pattern 0 (all grey), 'crane' itself
        should be eliminated (because no letters match)."""
        engine.reset()
        success = engine.update_state("crane", 0)
        assert success
        assert "crane" not in [
            engine.lex.solution_words[i] for i in engine.possible_indices
        ]

    def test_perfect_match_leaves_one(self, engine):
        """All-greens pattern (242) should leave only 'crane' as possible."""
        engine.reset()
        success = engine.update_state("crane", 242)
        assert success
        assert len(engine.possible_indices) == 1
        assert engine.lex.solution_words[engine.possible_indices[0]] == "crane"

    def test_invalid_pattern_returns_false(self, engine):
        """A pattern that matches zero words MUST return False.

        After an all-grey CRANE filter, CRANE is no longer in the pool, so
        feeding the all-green (242) pattern for CRANE must signal failure
        rather than silently producing an empty/garbage state.
        """
        engine.reset()
        engine.update_state("crane", 0)
        success = engine.update_state("crane", 242)
        assert success is False

    def test_turn_increments(self, engine):
        engine.reset()
        assert engine.turn == 1
        engine.update_state("crane", 0)
        assert engine.turn == 2

    def test_reset_restores_full_pool(self, engine):
        engine.reset()
        engine.update_state("crane", 0)
        assert len(engine.possible_indices) < len(engine.lex.solution_words)
        engine.reset()
        assert len(engine.possible_indices) == len(engine.lex.solution_words)
        assert engine.turn == 1


# ── get_suggestions ──────────────────────────────────────────────

class TestGetSuggestions:
    def test_returns_two_lists(self, engine):
        engine.reset()
        strat, cands = engine.get_suggestions()
        assert isinstance(strat, list)
        assert isinstance(cands, list)

    def test_top_strategic_has_ten_items(self, engine):
        engine.reset()
        strat, _ = engine.get_suggestions()
        assert len(strat) == 10

    def test_top_candidates_has_items(self, engine):
        engine.reset()
        _, cands = engine.get_suggestions()
        assert len(cands) > 0

    def test_results_have_required_keys(self, engine):
        engine.reset()
        strat, _ = engine.get_suggestions()
        for item in strat:
            assert "word" in item
            assert "score" in item
            assert "win_prob" in item
            assert "is_candidate" in item

    def test_sorted_by_score_descending(self, engine):
        engine.reset()
        strat, _ = engine.get_suggestions()
        scores = [item["score"] for item in strat]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_empty_pool_returns_empty(self, engine):
        engine.reset()
        # Force an empty state (answer-space)
        engine.possible_indices = np.array([], dtype=int)
        engine.possible_mask = np.zeros(len(engine.lex.solution_words), dtype=bool)
        strat, cands = engine.get_suggestions()
        assert strat == []
        assert cands == []

    def test_hard_mode_returns_suggestions(self, engine):
        engine.reset()
        strat, cands = engine.get_suggestions(is_hard_mode=True)
        assert len(strat) == 10

    def test_first_guess_returns_strategic(self, engine):
        """Turn-1 returns a full ranked list. The top STRATEGIC (SHRED)
        opener is any legal word; the top CANDIDATE (SOLVE) must be a
        real NYT answer (the solver never proposes a non-answer as THE
        answer)."""
        engine.reset()
        strat, cands = engine.get_suggestions()
        assert len(strat) == 10
        assert strat[0]["word"] in engine.all_words
        assert cands, "SOLVE panel should have candidates on turn 1"
        assert cands[0]["word"] in VALID_SOLUTIONS


# ── Integration: a full game ──────────────────────────────────

class TestFullGame:
    def test_solve_crane(self, engine):
        """Play through a full game with CRANE as secret."""
        engine.reset()
        secret = "crane"
        for turn in range(1, 7):
            strat, _ = engine.get_suggestions()
            assert strat, f"Failed on turn {turn}"
            guess = strat[0]["word"]
            if guess == secret:
                return  # Solved!
            pattern = engine.calculate_pattern(guess, secret)
            engine.update_state(guess, pattern)
        pytest.fail(f"Failed to solve '{secret}' within 6 turns")

    def test_solve_happy(self, engine):
        """Solve 'happy' (double letter case)."""
        engine.reset()
        secret = "happy"
        for turn in range(1, 7):
            strat, _ = engine.get_suggestions()
            assert strat, f"Failed on turn {turn}"
            guess = strat[0]["word"]
            if guess == secret:
                return
            pattern = engine.calculate_pattern(guess, secret)
            engine.update_state(guess, pattern)
        pytest.fail(f"Failed to solve '{secret}' within 6 turns")

    def test_solve_quickly(self, engine):
        """Solve 'audio' — should be fast (common letters)."""
        engine.reset()
        secret = "audio"
        for turn in range(1, 7):
            strat, _ = engine.get_suggestions()
            assert strat, f"Failed on turn {turn}"
            guess = strat[0]["word"]
            if guess == secret:
                return
            pattern = engine.calculate_pattern(guess, secret)
            engine.update_state(guess, pattern)
        pytest.fail(f"Failed to solve '{secret}' within 6 turns")

    def test_hard_mode_guess_is_pool_consistent(self, engine):
        """REGRESSION (D1): in hard mode every suggested guess must be a
        legal hard-mode word — i.e. consistent with all revealed clues.

        The candidate pool `possible_indices` is exactly the set of words
        consistent with every past pattern, so a legal hard-mode guess must
        belong to it. Samples real NYT answers (the solver's target).
        """
        import random
        random.seed(11)
        for secret in random.sample(VALID_SOLUTIONS, 40):
            engine.reset()
            for turn in range(1, 7):
                strat, _ = engine.get_suggestions(is_hard_mode=True)
                assert strat, f"No suggestions for '{secret}' on turn {turn}"
                guess = strat[0]["word"]
                # Legal hard-mode guess ⟺ in the current candidate pool.
                assert guess in [
                    engine.lex.solution_words[i] for i in engine.possible_indices
                ], (
                    f"Hard-mode guess '{guess}' for secret '{secret}' is not "
                    f"pool-consistent (would violate NYT hard rule)"
                )
                if guess == secret:
                    break
                pattern = engine.calculate_pattern(guess, secret)
                engine.update_state(guess, pattern)


# ── Endgame shortcut (pool <= 2) ──────────────────────────────

class TestEndgameShortcut:
    def test_two_candidate_pool_returns_them_by_posterior(self, engine):
        """REGRESSION (endgame fix): when <=2 answers remain, suggestions
        must be exactly those candidates, ranked by posterior — not gated
        by global frequency (which would favour a common non-candidate)."""
        engine.reset()
        # narrow to exactly two answers
        survivors = engine.lex.solution_words[:2]
        engine.possible_indices = np.array(
            [engine.lex.solution_words.index(w) for w in survivors]
        )
        engine.possible_mask = np.zeros(engine.n_sol, dtype=bool)
        engine.possible_mask[engine.possible_indices] = True
        engine.turn = 4
        engine._mark_aop_dirty()
        strat, cands = engine.get_suggestions()
        assert len(strat) == 2
        assert {s["word"] for s in strat} == set(survivors)
        assert all(s["is_candidate"] for s in strat)
        # descending by win_prob
        wp = [s["win_prob"] for s in strat]
        assert wp == sorted(wp, reverse=True)

    def test_single_candidate_pool(self, engine):
        engine.reset()
        only = engine.lex.solution_words[7]
        idx = engine.lex.solution_words.index(only)
        engine.possible_indices = np.array([idx])
        engine.possible_mask = np.zeros(engine.n_sol, dtype=bool)
        engine.possible_mask[idx] = True
        engine.turn = 5
        engine._mark_aop_dirty()
        strat, cands = engine.get_suggestions()
        assert strat[0]["word"] == only


# ── Hard mode mid-game legality ──────────────────────────────

class TestHardModeMidGame:
    def test_midgame_guess_is_pool_consistent(self, engine):
        """REGRESSION (D1): at turn >= 3 in hard mode, every suggested
        guess must still belong to the current candidate pool."""
        import random
        random.seed(3)
        for secret in random.sample(VALID_SOLUTIONS, 25):
            engine.reset()
            for turn in range(1, 7):
                strat, _ = engine.get_suggestions(is_hard_mode=True)
                assert strat, f"No suggestions for '{secret}' turn {turn}"
                guess = strat[0]["word"]
                pool_words = [
                    engine.lex.solution_words[i] for i in engine.possible_indices
                ]
                assert guess in pool_words, (
                    f"Hard-mode guess '{guess}' not pool-consistent at turn {turn}"
                )
                if guess == secret:
                    break
                engine.update_state(guess, engine.calculate_pattern(guess, secret))


# ── Hard-mode small-pool splitter (tightness regression) ──────

class TestHardModeSmallPool:
    def test_small_pool_prefers_best_splitter(self, engine):
        """REGRESSION (tightness audit): in hard mode with a small pool,
        the engine must rank by worst-case bucket size (best splitter), not
        pure frequency — otherwise tight sibling clusters (hatch/latch/match)
        get peeled one-per-turn and miss the 6-move cap. Forcing a small
        pool of near-identical words, the top suggestion must be a pool
        member that minimises the largest pattern group it leaves behind.
        """
        engine.reset()
        # A real tight 7-word sibling cluster (hatch/latch are genuine
        # hard-mode failures the audit surfaced).
        cluster = ["batch", "catch", "hatch", "latch", "match", "patch", "watch"]
        idxs = np.array([engine.lex.solution_words.index(w) for w in cluster])
        engine.possible_indices = idxs
        engine.possible_mask = np.zeros(engine.n_sol, dtype=bool)
        engine.possible_mask[idxs] = True
        engine.turn = 5
        engine._mark_aop_dirty()
        strat, _ = engine.get_suggestions(is_hard_mode=True)
        assert strat
        # every suggestion is a pool member
        assert all(s["word"] in cluster for s in strat)
        # top pick minimises worst-case bucket (verified vs brute below)
        pat = engine.pm.rows(idxs, idxs)
        worst = {}
        for gi, g in enumerate(cluster):
            _, counts = np.unique(pat[gi], return_counts=True)
            worst[g] = int(counts.max())
        best = min(worst.values())
        assert worst[strat[0]["word"]] == best
        # ranking is by (worst-case asc, then win_prob desc)
        keys = [(worst[s["word"]], -s["win_prob"]) for s in strat]
        assert keys == sorted(keys)


# ── Hints (NYT hint button) ──────────────────────────────────

class TestHints:
    """NYT hint feature: the in-game button reveals exactly one consonant
    AND one vowel (2 total). The engine prunes the pool and honors the
    hinted letters in suggestions, in both modes, at any point in play.
    """

    def test_hint_turn1_honored(self, engine):
        engine.reset()
        assert engine.add_hint("a") is True
        strat, _ = engine.get_suggestions()
        assert strat, "no suggestions after hint"
        assert all("a" in r["word"] for r in strat), "turn-1 hint not honored"

    def test_hint_midgame_prunes_pool(self, engine):
        engine.reset()
        s, _ = engine.get_suggestions()
        engine.update_state(s[0]["word"], engine.calculate_pattern(s[0]["word"], "crane"))
        before = len(engine.possible_indices)
        engine.add_hint("z")
        after = len(engine.possible_indices)
        assert after < before, "hint should prune the pool"
        assert all("z" in engine.lex.solution_words[i] for i in engine.possible_indices)
        strat, _ = engine.get_suggestions()
        assert all("z" in r["word"] for r in strat)

    def test_hint_honored_in_both_modes(self, engine):
        import random
        random.seed(5)
        for is_hard in (False, True):
            for secret in random.sample(VALID_SOLUTIONS, 15):
                engine.reset()
                # 1 consonant + 1 vowel from the secret (valid NYT hint)
                cons = next((c for c in dict.fromkeys(secret)
                           if c in "bcdfghjklmnpqrstvwxyz"), None)
                vow = next((c for c in dict.fromkeys(secret)
                           if c in "aeiou"), None)
                assert cons and vow, "secret must have both"
                assert engine.add_hint(cons) is True
                assert engine.add_hint(vow) is True
                for turn in range(1, 7):
                    strat, _ = engine.get_suggestions(is_hard_mode=is_hard)
                    assert strat, f"no suggestions (hard={is_hard})"
                    guess = strat[0]["word"]
                    assert cons in guess and vow in guess, (
                        f"hinted letter missing in guess '{guess}' (hard={is_hard})"
                    )
                    if guess == secret:
                        break
                    engine.update_state(guess, engine.calculate_pattern(guess, secret))

    def test_hint_restricted_one_consonant_one_vowel(self, engine):
        """NYT rule: exactly one consonant AND one vowel (2 total).
        A 2nd consonant or 2nd vowel must be rejected; budget then spent.
        """
        engine.reset()
        assert engine.add_hint("a") is True   # vowel #1
        assert engine.add_hint("e") is False  # 2nd vowel -> rejected
        assert engine.add_hint("b") is True   # consonant #1
        assert engine.add_hint("c") is False  # 2nd consonant -> rejected
        assert engine.add_hint("a") is False  # duplicate / budget spent
        assert engine.add_hint("z") is False  # budget already spent (1+1)
        assert engine.hinted_letters == {"a", "b"}

    def test_hint_contradiction_rejected(self, engine):
        engine.reset()
        engine.update_state("crane", 0)  # all-grey: drops words with c/r/a/n/e
        assert engine.add_hint("e") is False  # no survivor contains 'e'
        assert len(engine.possible_indices) > 0
        assert "e" not in engine.hinted_letters

    def test_hint_invalid_input(self, engine):
        engine.reset()
        assert engine.add_hint("") is False
        assert engine.add_hint("ab") is False
        assert engine.add_hint("1") is False
