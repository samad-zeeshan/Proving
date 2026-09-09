"""Paired bootstrap intervals, Wilson bounds and the three-way hypothesis verdict."""

from __future__ import annotations

import random
from statistics import NormalDist, fmean

RESAMPLES = 4000


def z_for(level: float) -> float:
    return NormalDist().inv_cdf(0.5 + level / 2)


def bootstrap_delta(a: list[float], b: list[float], *, level: float = 0.95, seed: int = 7,
                    resamples: int = RESAMPLES) -> dict:
    """Mean of b minus a over the same scenarios, with a percentile interval from resampling scenarios.

    Resampling pairs, not the two arms apart, keeps what a scenario makes easy or hard out of the noise.
    """
    if len(a) != len(b):
        raise ValueError("a paired comparison needs the same scenarios in both arms")
    n = len(a)
    if n == 0:
        return {"delta": None, "lo": None, "hi": None, "n": 0, "level": level}
    diffs = [y - x for x, y in zip(a, b)]
    rng = random.Random(seed)
    means = sorted(fmean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(resamples))
    tail = (1 - level) / 2
    lo = means[int(tail * resamples)]
    hi = means[min(resamples - 1, int((1 - tail) * resamples))]
    return {"delta": round(fmean(diffs), 6), "lo": round(lo, 6), "hi": round(hi, 6), "n": n, "level": level}


def improvements(a: list[float], b: list[float], direction: str) -> list[float]:
    return [(y - x) if direction == "increase" else (x - y) for x, y in zip(a, b)]


def verdict(lo: float, hi: float, min_effect: float) -> str:
    # Confirmed: the whole interval says the change helps. Refuted: the interval rules out a help at
    # least as big as the smallest effect worth shipping for. Anything else needs more scenarios.
    if lo > 0:
        return "confirmed"
    if hi < min_effect:
        return "refuted"
    return "underpowered"


def wilson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    z = z_for(level)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, round(centre - half, 6)), min(1.0, round(centre + half, 6))


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 3)
