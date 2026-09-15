"""Every number in the README comes from eval/results, and nothing outside the results block drifts."""

import re
from pathlib import Path

import pytest

from proving.report import readme

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
RESULTS = REPO / "eval" / "results"


@pytest.mark.skipif(not (RESULTS / "parley" / "rules-vs-llm.json").exists(), reason="results not generated")
def test_results_block_matches_the_results_files():
    text = README.read_text(encoding="utf-8")
    assert readme.splice(text, readme.render(RESULTS)) == text


def test_no_numbers_outside_the_generated_block():
    text = README.read_text(encoding="utf-8")
    head, rest = text.split(readme.BEGIN, 1)
    _, tail = rest.split(readme.END, 1)
    outside = head + tail
    # Allowed: arXiv ids, the demo recording's length, and file names like demo.mp4.
    cleaned = re.sub(r"\d{4}\.\d{5}|90-second|mp4|\.png|\(\d+\)", "", outside)
    assert re.findall(r"\d", cleaned) == []


def test_readme_is_short():
    assert len(README.read_text(encoding="utf-8").splitlines()) < 120
