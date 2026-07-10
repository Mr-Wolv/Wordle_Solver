"""Tests for cli.py pattern parsing and validation helpers.

cli.parse_pattern converts the 5-char "02220" string into a base-3 int.
This is the boundary between the user's typed input and the engine's
integer pattern, so malformed input must be rejected loudly.
"""
import pytest

from cli import parse_pattern


def test_parse_all_grey():
    assert parse_pattern("00000") == 0


def test_parse_all_green():
    # 2 + 2*3 + 2*9 + 2*27 + 2*81 = 242
    assert parse_pattern("22222") == 242


def test_parse_mixed():
    # '02220' -> p = [0,2,2,2,0] -> 0 + 6 + 18 + 54 + 0 = 78
    assert parse_pattern("02220") == 78


def test_parse_single_green_at_edge():
    # '20000' -> 2*1 = 2
    assert parse_pattern("20000") == 2


def test_parse_wrong_length():
    with pytest.raises(ValueError):
        parse_pattern("0222")
    with pytest.raises(ValueError):
        parse_pattern("022200")


def test_parse_invalid_digit():
    with pytest.raises(ValueError):
        parse_pattern("02223")  # '3' is not a valid colour
    with pytest.raises(ValueError):
        parse_pattern("0222x")
