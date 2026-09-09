"""Bootstrap intervals, Wilson bounds, hypothesis verdicts and the evidence bar."""

import pytest

from proving.report import enterprise
from proving.scoring import stats


def test_bootstrap_is_seeded_and_brackets_the_difference():
    a = [0] * 50 + [1] * 50
    b = [0] * 20 + [1] * 80
    one = stats.bootstrap_delta(a, b, seed=3)
    two = stats.bootstrap_delta(a, b, seed=3)
    assert one == two
    assert one["delta"] == pytest.approx(0.30)
    assert one["lo"] < 0.30 < one["hi"]
    assert one["lo"] > 0


def test_paired_bootstrap_needs_equal_lengths():
    with pytest.raises(ValueError):
        stats.bootstrap_delta([1, 0], [1])


def test_identical_versions_give_a_zero_interval():
    out = stats.bootstrap_delta([1, 0, 1, 1], [1, 0, 1, 1])
    assert out["delta"] == 0 and out["lo"] == 0 and out["hi"] == 0


def test_wilson_bounds():
    lo, hi = stats.wilson(0, 100, 0.95)
    assert lo == 0 and hi == pytest.approx(0.037, abs=0.001)
    lo, hi = stats.wilson(50, 100, 0.95)
    assert lo == pytest.approx(0.404, abs=0.002) and hi == pytest.approx(0.596, abs=0.002)


@pytest.mark.parametrize("lo, hi, verdict", [
    (0.01, 0.10, "confirmed"),
    (-0.05, 0.02, "refuted"),      # an improvement of 0.05 or more is ruled out
    (-0.20, -0.05, "refuted"),     # clearly worse
    (-0.02, 0.12, "underpowered"),
])
def test_verdict_rule(lo, hi, verdict):
    assert stats.verdict(lo, hi, min_effect=0.05) == verdict


def test_improvement_flips_sign_for_decrease():
    a, b = [3, 2, 4], [1, 1, 2]
    assert stats.improvements(a, b, "decrease") == [2, 1, 2]
    assert stats.improvements(a, b, "increase") == [-2, -1, -2]


def test_percentiles():
    assert stats.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert stats.percentile([], 0.5) is None


def test_evidence_bar_rises_with_consequence_and_autonomy():
    low = enterprise.evidence_bar("A1", "low")
    high = enterprise.evidence_bar("A3", "high")
    assert low["tier"] == "light" and high["tier"] == "strict"
    assert high["confidence"] > low["confidence"]
    assert high["max_hazard_rate"] < low["max_hazard_rate"]
    assert enterprise.evidence_bar("A3", "low")["tier"] == "standard"
