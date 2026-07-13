"""Cached, six-domain exhaustive accuracy gate.

This is the load-bearing 100% proof the solver's accuracy claims rest on.
It replays, for EACH of the six locked domains, every official NYT answer
with the exact hint enumerations the request specifies:

    M1 normal·0 : 2,315 games, no hints
    M2 hard·0   : 2,315 games, no hints
    M3 normal·1 : for each word, EVERY distinct letter of the word (each
                  vowel alone, each consonant alone) -> ~ avg 5 games/word
    M4 hard·1   : same 1-hint enumeration, hard mode
    M5 normal·2 : for each word, EVERY (vowel x consonant) pair drawn from
                  the word's own letters (the NYT 1-cons+1-vow rule)
    M6 hard·2   : same 2-hint enumeration, hard mode

that is ~50k+ simulated games. The FIRST run computes them and writes a
version-stamped cache to disk (keyed by a hash of the engine + data +
mode logic). EVERY later run reads the cache and verifies the same 100%
in milliseconds — so the "hours above hours" cost is paid exactly once.

The exhaustive gate is part of the DEFAULT `pytest` run (no addopts
exclusion in pytest.ini — it was removed so `pytest` proves the full
contract every time). For a fast smoke test, run `pytest -m "not exhaustive"`
or bound the corpus with WS_GATE_LIMIT=N.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import concurrent.futures as cf
from typing import Iterable

import pytest

from wordle_solver.engine.modes import VOWELS, CONSONANTS, MODE_ORDER
from wordle_solver.engine.game import play_mode
from wordle_solver.utils import data_path

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gate_cache")
_LIMIT = int(os.environ.get("WS_GATE_LIMIT", "0"))  # 0 = full corpus

# The six domains in canonical order.
DOMAINS = MODE_ORDER  # normal_0, hard_0, normal_1, hard_1, normal_2, hard_2


def _load_words() -> list[str]:
    raw = __import__("pandas").read_csv(
        data_path("valid_solutions.csv")).iloc[:, 0].tolist()
    # Drop the CSV header row ("word") and any junk (non-alpha / not 5 long);
    # the engine's answer space is exactly the 2,315 real solutions.
    words = [str(x).strip().lower() for x in raw]
    words = [w for w in words if w.isalpha() and len(w) == 5 and w != "word"]
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    if _LIMIT:
        out = out[:_LIMIT]
    return out


def _pairs_for_word(word: str, mode_key: str) -> list[tuple[str, str, list[str]]]:
    """(word, mode_to_play, hint_set) for every hint set this word must satisfy.

    Mode 0 -> one game, no hints.
    Mode 1 -> every distinct letter of the word.
    Mode 2 -> every (vowel x consonant) pair. Vowel-less words (e.g. glyph,
    myrrh) have NO valid 2-hint combo under the NYT rule, so NYT only ever
    reveals a single valid letter; we fall back to the 1-hint domain (every
    distinct letter) so the word is genuinely verified rather than skipped.
    Consonant-less words (none in the list, but handled symmetrically) hit the
    same empty-vxc fallback. Each returned triple is fed to
    play_mode(word, mode, hint_letters=hs).
    """
    budget = int(mode_key.split("_")[1])
    if budget == 0:
        return [(word, mode_key, [])]
    if budget == 1:
        return [(word, mode_key, hs) for hs in _hint_sets(word, 1)]
    # budget == 2
    hs2 = _hint_sets(word, 2)
    if hs2:
        return [(word, mode_key, hs) for hs in hs2]
    one_mode = mode_key.replace("_2", "_1")
    return [(word, one_mode, hs) for hs in _hint_sets(word, 1)]


def _hint_sets(word: str, budget: int) -> list[list[str]]:
    """Hint sets for a word under the NYT rule, per the request."""
    vs = sorted({c for c in word if c in VOWELS})
    cs = sorted({c for c in word if c in CONSONANTS})
    if budget == 0:
        return [[]]
    if budget == 1:
        # every distinct letter (each vowel alone, each consonant alone)
        return [[v] for v in vs] + [[c] for c in cs]
    # budget == 2: every (vowel x consonant) pair
    out = [[v, c] for v in vs for c in cs]
    return out  # may be empty for all-consonant words (no valid 2-hint combo)


def _version_hash() -> str:
    """Hash of engine + data + mode logic so the cache invalidates on change."""
    h = hashlib.sha256()
    import wordle_solver.engine as eng_pkg
    import wordle_solver.engine.modes as modes_mod
    import wordle_solver.engine.game_mode as gm_mod
    import wordle_solver.engine.game as game_mod
    for mod in (eng_pkg, modes_mod, gm_mod, game_mod):
        f = mod.__file__
        try:
            if not f:
                src = repr(mod).encode()
            else:
                with open(f, "rb") as fh:
                    src = fh.read()
        except Exception:
            src = repr(mod).encode()
        h.update(src)
    # fold in the data artifacts that drive solver behavior
    for f in ("residual_optimal.json", "residual_optimal_nohint.json",
              "residual_optimal_1hint.json", "residual_optimal_2hint.json",
              "t1_h_opening.json", "valid_solutions.csv"):
        try:
            with open(data_path(f), "rb") as fh:
                h.update(fh.read())
        except Exception:
            pass
    h.update(b"v3-six-domain-locked")  # bump on contract change
    return h.hexdigest()[:16]


def _cache_path(version: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"gate_{version}.json")


# Checkpoint the cache every this many completed (word,hint-set) games so a
# long full run is crash-safe and a monitor can watch progress live.
_CHECKPOINT_EVERY = int(os.environ.get("WS_GATE_CHECKPOINT", "1000"))


def _atomic_write_cache(path: str, cache: dict) -> None:
    """Write via temp+rename so a concurrent reader never sees a half file."""
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(cache, fh)
    os.replace(tmp, path)


def _load_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def _checkpoint(path: str, mode_key: str, cached: dict | None,
                results: dict[str, int]) -> None:
    """Merge current partial results into the on-disk cache (never shrink)."""
    cache = _load_cache(path)
    merged = dict(cache.get(mode_key) or cached or {})
    merged.update(results)
    cache[mode_key] = merged
    _atomic_write_cache(path, cache)


def _compute_mode(mode_key: str, words: list[str]) -> dict[str, int]:
    """Replay every (word, hint-set) for one domain. Returns word->turns."""
    results: dict[str, int] = {}
    for w in words:
        best = 0
        played = False
        for _, m, hs in _pairs_for_word(w, mode_key):
            _, turns = play_mode(w, m, hint_letters=hs if hs else None)
            played = True
            # record worst (a domain "passes" only if EVERY hint set solves)
            if turns > best:
                best = turns
        # never let an unplayed word masquerade as a pass
        results[w] = best if played else 7
    return results


def _run_domain(mode_key: str, words: list[str], force: bool) -> dict[str, int]:
    version = _version_hash()
    path = _cache_path(version)
    # A cache entry is only usable if it COVERS every requested word — a
    # 60-word slice must never satisfy a 2,315-word exhaustive request.
    cached = _load_cache(path).get(mode_key)
    if cached and not force and set(words) <= set(cached):
        return {w: cached[w] for w in words}
    # compute (optionally in parallel across words for speed on the one-time run)
    # Each triple is (word, mode_to_play, hint_set); the mode may differ from
    # mode_key for vowel-less words (2-hint falls back to the 1-hint domain).
    pairs = [(w, m, hs) for w in words for w, m, hs in _pairs_for_word(w, mode_key)]
    results: dict[str, int] = {}
    done = 0
    if len(pairs) > 200:
        # parallel for the expensive (cache-miss) path
        with cf.ProcessPoolExecutor() as ex:
            futs = {ex.submit(play_mode, w, m, hs if hs else None): w
                    for w, m, hs in pairs}
            for fut in cf.as_completed(futs):
                w = futs[fut]
                _, turns = fut.result()
                if w not in results or turns > results[w]:
                    results[w] = turns
                done += 1
                if done % _CHECKPOINT_EVERY == 0:
                    _checkpoint(path, mode_key, cached, results)
    else:
        for w, m, hs in pairs:
            _, turns = play_mode(w, m, hint_letters=hs if hs else None)
            if w not in results or turns > results[w]:
                results[w] = turns
            done += 1
            if done % _CHECKPOINT_EVERY == 0:
                _checkpoint(path, mode_key, cached, results)
    # guarantee every requested word is present (never an unplayed false pass)
    for w in words:
        results.setdefault(w, 7)
    # Final merge (never shrink): a full run supersedes a slice; a later slice
    # can't clobber the full proof.
    _checkpoint(path, mode_key, cached, results)
    return results


# ── property: every domain must solve 100% (all turns <= 6) ──────
@pytest.mark.parametrize("mode_key", DOMAINS)
@pytest.mark.exhaustive
def test_domain_solves_100(mode_key):
    words = _load_words()
    results = _run_domain(mode_key, words, force=False)
    failures = [w for w, t in results.items() if t > 6]
    assert not failures, f"{mode_key} regressed: {failures[:20]}"


# ── fast subset (default run): prove the harness + 100% on a slice,
#     reading the versioned cache when present so repeat runs are instant.
@pytest.mark.parametrize("mode_key", DOMAINS)
def test_domain_solves_100_fast_subset(mode_key):
    words = _load_words()[:60]
    results = _run_domain(mode_key, words, force=False)
    failures = [w for w, t in results.items() if t > 6]
    assert not failures, f"{mode_key} regressed on subset: {failures[:20]}"
