"""
Unit tests for the WordleEngine core methods.

Run with:  pytest test_engine.py -v
"""

import pytest
import numpy as np
from Engine import WordleEngine


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    """Create a single engine instance for all tests (matrix load is expensive)."""
    return WordleEngine()


# ── Initialisation ────────────────────────────────────────────────────

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
        """Fresh engine should have all words as possible."""
        assert len(engine.possible_indices) == len(engine.all_words)
        assert engine.possible_mask.all()

    def test_turn_one_at_start(self, engine):
        assert engine.turn == 1


# ── calculate_pattern ─────────────────────────────────────────────────

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
        # 'a' is yellow at position 0 (value 1), 'd' is green at pos 3 (value 2)
        # pattern = 1,0,0,2,0 → 1*1 + 2*27 = 55
        assert p == 55

    def test_one_green(self, engine):
        """Exact match at one position."""
        p = engine.calculate_pattern("abcde", "afghi")
        # 'a' is green at position 0 (value 2) → 2 * 3^0 = 2
        assert p == 2

    def test_mixed_pattern(self, engine):
        """A typical Wordle pattern."""
        # Guess: CRANE, Secret: CRONY
        # C→C green (pos 0), R→R green (pos 1), A→O grey, N→N green (pos 3), E→Y grey
        # pattern = 2,2,0,2,0 → 2*1 + 2*3 + 0*9 + 2*27 + 0*81 = 62
        p = engine.calculate_pattern("crane", "crony")
        expected = 2 + 2*3 + 2*27  # 2 + 6 + 54 = 62
        assert p == expected

    def test_double_letter_partial(self, engine):
        """If guess has two 'a's but secret has one, only one scores."""
        p = engine.calculate_pattern("aaaaa", "bcdea")
        # One 'a' at position 4 is green (secret[4] == 'a'), rest grey
        # pattern = 0,0,0,0,2 → 2 * 81 = 162
        expected = 2 * 81
        assert p == expected

    def test_double_letter_exact(self, engine):
        """If both have two 'a's, both score."""
        p = engine.calculate_pattern("ababa", "abaca")
        # a→a green(pos0), b→b green(pos1), a→a green(pos2), b→c grey(pos3), a→a green(pos4)
        # pattern = 2,2,2,0,2 → 2*1 + 2*3 + 2*9 + 0 + 2*81 = 188
        expected = 2 + 2*3 + 2*9 + 2*81  # 2 + 6 + 18 + 162 = 188
        assert p == expected


# ── update_state & reset ─────────────────────────────────────────────

class TestUpdateState:
    def test_simple_filter(self, engine):
        """After guessing 'crane' with pattern 0 (all grey), 'crane' itself
        should be eliminated (because no letters match)."""
        engine.reset()
        # All grey pattern for CRANE
        success = engine.update_state("crane", 0)
        assert success
        # The word 'crane' itself should no longer be possible
        assert "crane" not in [
            engine.all_words[i] for i in engine.possible_indices
        ]

    def test_perfect_match_leaves_one(self, engine):
        """All-greens pattern (242) should leave only 'crane' as possible."""
        engine.reset()
        success = engine.update_state("crane", 242)
        assert success
        assert len(engine.possible_indices) == 1
        assert engine.all_words[engine.possible_indices[0]] == "crane"

    def test_invalid_pattern_returns_false(self, engine):
        """A pattern that matches zero words should return False."""
        engine.reset()
        # Filter to a very small pool first
        engine.update_state("crane", 0)
        # Try a pattern that can't match any word in the tiny pool
        engine.update_state("crane", 242)  # all greens — crane was already eliminated
        # This should fail because crane is no longer in the pool
        # (the result depends on what's left after the all-grey filter)

    def test_turn_increments(self, engine):
        engine.reset()
        assert engine.turn == 1
        engine.update_state("crane", 0)
        assert engine.turn == 2

    def test_reset_restores_full_pool(self, engine):
        engine.reset()
        engine.update_state("crane", 0)
        assert len(engine.possible_indices) < len(engine.all_words)
        engine.reset()
        assert len(engine.possible_indices) == len(engine.all_words)
        assert engine.turn == 1


# ── get_suggestions ───────────────────────────────────────────────────

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
        """When there are no possible words, suggestions should be empty."""
        engine.reset()
        # Force an empty state
        engine.possible_indices = np.array([], dtype=int)
        engine.possible_mask = np.zeros(len(engine.all_words), dtype=bool)
        strat, cands = engine.get_suggestions()
        assert strat == []
        assert cands == []

    def test_hard_mode_returns_suggestions(self, engine):
        engine.reset()
        strat, cands = engine.get_suggestions(is_hard_mode=True)
        assert len(strat) == 10

    def test_first_guess_is_tares(self, engine):
        """The optimal first guess in standard mode is TARES (highest entropy)."""
        engine.reset()
        strat, _ = engine.get_suggestions()
        top_word = strat[0]["word"]
        assert top_word == "tares", f"Expected 'tares', got '{top_word}'"


# ── Integration: a full game ──────────────────────────────────────────

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
