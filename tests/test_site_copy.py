"""Keep internal names out of the demo page's labels.

The recorded data still uses ids like resolver-off. The page must map each one to a plain label.
"""

import json
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
BANNED = ["hypothesis resolver", "hazard-run rate", "drop in planted calls", "adversarial persona"]


def _source() -> str:
    return "\n".join((SITE / name).read_text(encoding="utf-8") for name in ("index.html", "app.js"))


def test_banned_phrases_are_not_in_the_page():
    text = _source().lower()
    assert [b for b in BANNED if b in text] == []


def test_resolver_off_is_never_a_label():
    text = _source()
    # Allowed only as a key of a label map, where it becomes a small tag next to the plain name.
    assert re.findall(r'"resolver-off"(?!:)', text) == []
    assert ">resolver-off<" not in text


def test_every_recorded_version_has_a_plain_label():
    app = (SITE / "app.js").read_text(encoding="utf-8")
    labels = app.split("const VERSION = {", 1)[1].split("};", 1)[0]
    for client in ("warden", "parley"):
        data = json.loads((SITE / "data" / f"{client}.json").read_text(encoding="utf-8"))
        versions = set(data["versions"])
        if data.get("regression"):
            versions |= {data["regression"]["recorded_version"], data["regression"]["changed_version"]}
        for v in versions:
            assert re.search(rf'(^|\s)"?{re.escape(v)}"?:', labels, re.M), f"{client}: no plain label for {v}"


def test_every_gate_is_rewritten():
    app = (SITE / "app.js").read_text(encoding="utf-8")
    for client in ("warden", "parley"):
        data = json.loads((SITE / "data" / f"{client}.json").read_text(encoding="utf-8"))
        for gate in data["report"]["gates"]:
            name = gate["gate"]
            assert name.startswith("hypothesis") or f'g.gate === "{name}"' in app, f"{client}: gate {name} shows raw"


# Plain-language checks for the README prose and the page strings.
FILLER = {"comprehensive", "robust", "seamless", "cutting-edge", "state-of-the-art", "powerful", "leverage",
          "utilize", "ensure", "delve", "showcase", "crucial", "various", "numerous", "simply", "just",
          "really", "basically", "actually"}
MAX_WORDS = 25


def _readme_prose() -> list[str]:
    text = (SITE.parent / "README.md").read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    keep = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("|", "#", "<!--", "!["))]
    return [re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", ln) for ln in keep]


def _page_strings() -> list[str]:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    out = [t for t in re.split(r"<[^>]+>", html) if t.strip()]
    out += re.findall(r'(?:content|alt|aria-label|title)="([^"]+)"', html)
    app = (SITE / "app.js").read_text(encoding="utf-8")
    # Only quoted strings with at least three words count as text a reader sees.
    for s in re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', app):
        s = re.sub(r"\$\{[^}]*\}", "X", s[0] or s[1])
        if len(s.split()) >= 3 and re.search(r"[A-Za-z]{2}", s) and not re.search(r"[{}<>=]|\w\(", s):
            out.append(s)
    return out


def _sentences(lines: list[str]) -> list[str]:
    return [s for ln in lines for s in re.split(r"(?<=[.!?])\s+", ln.strip()) if s]


def test_copy_has_no_long_sentences():
    long = [s for s in _sentences(_readme_prose() + _page_strings()) if len(s.split()) > MAX_WORDS]
    assert long == []


def test_copy_has_no_filler_words():
    words = {w for s in _readme_prose() + _page_strings() for w in re.findall(r"[a-z-]+", s.lower())}
    assert sorted(words & FILLER) == []


def test_copy_has_no_em_dash_or_semicolon():
    bad = [s for s in _readme_prose() + _page_strings() if "—" in s or ";" in s]
    assert bad == []


# A form of "be", then at most one word, then a past participle. Hyphenated words like made-up are adjectives.
PASSIVE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+\s+)?"
    r"(?:\w+ed|made|done|found|given|held|kept|left|run|seen|sent|shown|taken|written|built|caught)\b(?!-)",
    re.I,
)
PASSIVE_OK = {
    # "Not settled yet" is the fixed name of the third verdict. Here "settled" is a state, not an action.
    "The claim is not settled yet.",
    "is not settled yet",
}


def test_copy_has_no_passive_voice():
    hits = [s for s in _sentences(_readme_prose() + _page_strings()) if PASSIVE.search(s) and s not in PASSIVE_OK]
    assert hits == []
