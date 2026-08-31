"""Transcript channels for a voice agent: clean, word noise at a set rate, and split turns.

These isolate the dialogue model from speech recognition, as MTVA-Bench does (arXiv 2609.20152).
"""

from __future__ import annotations

import random

# Letters speech recognizers confuse, per script. Arabic pairs are close in sound, Latin ones in shape.
_AR = {"ح": "خ", "خ": "ح", "ع": "غ", "غ": "ع", "س": "ص", "ص": "س", "ت": "ط", "ط": "ت", "د": "ض", "ض": "د",
       "ذ": "ز", "ز": "ذ", "ق": "ك", "ك": "ق", "ب": "ت", "ن": "ت", "ر": "ز", "ي": "ب", "ة": "ه", "ا": "ى"}
_EN = {"a": "e", "e": "i", "i": "e", "o": "u", "u": "o", "b": "p", "p": "b", "d": "t", "t": "d", "s": "z",
       "z": "s", "v": "f", "f": "v", "m": "n", "n": "m", "r": "l", "l": "r", "g": "k", "k": "g"}


def _confuse(word: str, rng: random.Random) -> str:
    spots = [i for i, c in enumerate(word) if c.lower() in _EN or c in _AR]
    if not spots:
        return word
    i = rng.choice(spots)
    c = word[i]
    repl = _AR.get(c) or _EN.get(c.lower(), c)
    return word[:i] + repl + word[i + 1:]


def noisy(text: str, rate: float, rng: random.Random) -> str:
    """Corrupt about `rate` of the words: mostly a confused letter, sometimes a dropped or merged word."""
    words = text.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if rng.random() < rate:
            roll = rng.random()
            if roll < 0.6:
                out.append(_confuse(w, rng))
            elif roll < 0.8:
                pass
            elif i + 1 < len(words):
                out.append(w + words[i + 1])
                i += 1
            else:
                out.append(_confuse(w, rng))
        else:
            out.append(w)
        i += 1
    return " ".join(out)


def split(text: str) -> list[str]:
    """The same words as two messages cut near the middle, the way a caller pauses mid-sentence."""
    words = text.split()
    if len(words) < 4:
        return [text]
    mid = len(words) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    """Edit distance over words and the reference length, for the WER a channel actually produced."""
    r, h = ref.split(), hyp.split()
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1], len(r)
