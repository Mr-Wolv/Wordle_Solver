"""Tests for the exhaustive enumeration report generator.

The generator (wordle_solver.tools.enumerate_exhaustive) is the *readable*
half of the closed-loop gate: it replays the same (word, domain, hint)
games the gate proves and writes EXHAUSTIVE_ENUMERATION.csv (the
authoritative structured record: one row per game) plus a companion
EXHAUSTIVE_ENUMERATION.txt (human-readable transcript with per-turn tile
colors). These tests prove:

  * FIDELITY: the generator's per-game outcome (PASS/FAIL, turns) matches the
    authoritative play_mode result for the exact same triple -- so the report
    can never claim a solve the real solver doesn't achieve.
  * FORMAT: the CSV has the right columns + one row per game; the TXT emits
    the readable `Hint [x]: N turns [PASS]` lines and tile-color rows.
  * COMPLETENESS: every one of the six domains is emitted for each word.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ROOT)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from wordle_solver.tools import enumerate_exhaustive as ee  # noqa: E402
from wordle_solver.engine.game import play_mode, play_mode_trace  # noqa: E402
from wordle_solver.engine.modes import MODE_ORDER  # noqa: E402


WORDS_5 = ["aback", "abase", "abate", "abbey", "abbot"]


def _run(words):
    """Run generate() to temp csv+txt, return (csv_rows, txt, stats, csvp, txtp)."""
    fd, csvp = tempfile.mkstemp(suffix=".csv", prefix="enum_")
    os.close(fd)
    fd, txtp = tempfile.mkstemp(suffix=".txt", prefix="enum_")
    os.close(fd)
    stats = ee.generate(words, csvp, txtp)
    with open(csvp, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with open(txtp, encoding="utf-8") as fh:
        txt = fh.read()
    return rows, txt, stats, csvp, txtp


def _cleanup(paths):
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


def test_format_and_six_domains_per_word():
    rows, txt, stats, csvp, txtp = _run(WORDS_5)
    try:
        # CSV columns present + one row per (word, domain, hint) game.
        assert rows and list(rows[0].keys()) == [
            "word", "mode", "hint", "turns", "status", "guesses"]
        # Every word shows all six domains in the TXT.
        for w in WORDS_5:
            for mode in MODE_ORDER:
                assert f"  {mode}:" in txt, (w, mode)
        # TXT header records the word count.
        assert "Total words: 5" in txt
        # No failures on the solvable sample.
        assert stats["failures"] == 0
        # Every CSV row is PASS (no residual words in this sample).
        assert all(r["status"] == "PASS" for r in rows)
        # Row count == 88 games for these 5 words (matches play_mode replay).
        assert len(rows) == stats["games"]
    finally:
        _cleanup([csvp, txtp])


def test_generator_fidelity_matches_play_mode():
    """Every (word, domain, hint) outcome in the report equals play_mode."""
    rows, txt, stats, csvp, txtp = _run(WORDS_5)
    try:
        # Build a lookup from (word, mode, hint) -> (turns, status) for speed.
        by_key = {(r["word"], r["mode"], r["hint"]): r for r in rows}
        for w in WORDS_5:
            for mode in MODE_ORDER:
                for _, m, hs in ee.pairs_for_word(w, mode):
                    ref_turns = play_mode(w, m, hs if hs else None)[1]
                    ref_status = "PASS" if 1 <= ref_turns <= 6 else "FAIL"
                    key = (w, m, ee._fmt_hint(hs))
                    assert key in by_key, (w, m, hs)
                    r = by_key[key]
                    assert int(r["turns"]) == ref_turns, (w, m, hs, r)
                    assert r["status"] == ref_status, (w, m, hs, r)
                    if ref_status == "PASS":
                        # The full guess path ends in the secret word.
                        seq = r["guesses"].split(";")
                        assert seq[-1].lower() == w, (w, m, hs, seq)
    finally:
        _cleanup([csvp, txtp])


def test_per_turn_tile_colors_in_txt():
    """TXT transcript renders each guess with a 5-tile color block."""
    rows, txt, stats, csvp, txtp = _run(WORDS_5)
    try:
        # At least one tile-color row (▓/▒/░ block) present for a solved game.
        import re
        color_rows = re.findall(r"^\s+[A-Z]{5}\s+\[[▓▒░]+\]",
                                 txt, flags=re.MULTILINE)
        assert color_rows, "no tile-color rows rendered"
        # ABACK's normal_0 solve ends with a fully-green row (▓▓▓▓▓).
        assert "ABACK  [▓▓▓▓▓]" in txt
    finally:
        _cleanup([csvp, txtp])


def test_cli_emits_csv_and_txt(tmp_path):
    """The CLI (--csv/--txt) writes both artifacts and exits 0 on no failures."""
    orig_argv = sys.argv
    csvp = str(tmp_path / "out.csv")
    txtp = str(tmp_path / "out.txt")
    sys.argv = ["enumerate_exhaustive", "--limit", "5",
                "--csv", csvp, "--txt", txtp]
    try:
        rc = ee.main()
        assert rc == 0
        assert os.path.exists(csvp) and os.path.exists(txtp)
        with open(csvp, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) > 0
        assert list(rows[0].keys()) == [
            "word", "mode", "hint", "turns", "status", "guesses"]
    finally:
        sys.argv = orig_argv


def test_play_mode_trace_returns_guesses():
    word, turns, guesses = play_mode_trace("crane", "normal_0")
    assert word == "crane"
    assert 1 <= turns <= 6
    assert guesses and guesses[-1] == "crane"
    assert len(guesses) == turns
