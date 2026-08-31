"""Fill phrasebook templates like "{budget|thousands}" or "{date.day}" from a persona's facts."""

from __future__ import annotations

import re
from typing import Any

_FIELD = re.compile(r"\{([A-Za-z_][\w.]*)(?:\|(\w+))?\}")

_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
          "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _below_hundred(n: int) -> str:
    if n < 10:
        return _UNITS[n]
    if n < 20:
        return _TEENS[n - 10]
    return _TENS[n // 10] + (f" {_UNITS[n % 10]}" if n % 10 else "")


def en_thousands(n: int) -> str:
    """Budgets the way a caller says them: 120000 is "one hundred and twenty thousand"."""
    k = n // 1000
    hundreds, rest = divmod(k, 100)
    parts = [f"{_UNITS[hundreds]} hundred"] if hundreds else []
    if rest:
        parts.append(("and " if hundreds else "") + _below_hundred(rest))
    return " ".join(parts) + " thousand"


def _lookup(facts: dict, path: str) -> Any:
    cur: Any = facts
    for part in path.split("."):
        cur = cur[part]
    return cur


def _translate(value: Any, key: str, lang: dict) -> Any:
    table = (lang.get("values") or {}).get(key)
    if not table or isinstance(value, (dict, list)):
        return value
    if value in table:
        return table[value]
    return table.get(str(value), value)


def _filter(name: str, value: Any, lang: dict) -> str:
    if name == "digits":
        words = (lang.get("values") or {}).get("digit", _UNITS)
        return " ".join(words[int(c)] for c in str(value) if c.isdigit())
    if name == "thousands":
        return en_thousands(int(value))
    if name == "k":
        return str(int(value) // 1000)
    if name == "n":
        return str(value)
    raise KeyError(f"unknown filter {name!r}")


def fill(template: str, facts: dict, lang: dict) -> str:
    def one(m: re.Match) -> str:
        path, filt = m.group(1), m.group(2)
        value = _lookup(facts, path)
        if filt:
            return _filter(filt, value, lang)
        return str(_translate(value, path.split(".")[-1], lang))

    return _FIELD.sub(one, template)
