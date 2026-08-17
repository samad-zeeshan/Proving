"""A small predicate language over the final state: a dotted path, an operator and a value.

Predicates combine with all, any and not. Scenario files use it for success criteria and hazards.
"""

from __future__ import annotations

from typing import Any

from .schema import SchemaError

_MISSING = object()


def resolve(state: Any, path: str) -> Any:
    cur = state
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _order(op: str, a: Any, b: Any) -> bool:
    # Ordering against a missing or non-numeric value is false, never an exception. A hazard that
    # asks for "more than one booking" must not fire, or crash, on a run that never reached the API.
    if not (_num(a) and _num(b)):
        return False
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def _value(a: Any) -> Any:
    return None if a is _MISSING else a


OPS = {
    "eq": lambda a, b: _value(a) == b,
    "ne": lambda a, b: _value(a) != b,
    "in": lambda a, b: a is not _MISSING and a in b,
    "not_in": lambda a, b: a is _MISSING or a not in b,
    "contains": lambda a, b: isinstance(a, (list, str, dict)) and b in a,
    "exists": lambda a, b: (_value(a) is not None) == bool(b),
    "gt": lambda a, b: _order("gt", a, b),
    "gte": lambda a, b: _order("gte", a, b),
    "lt": lambda a, b: _order("lt", a, b),
    "lte": lambda a, b: _order("lte", a, b),
}


def check(pred: dict) -> None:
    if not isinstance(pred, dict):
        raise SchemaError(f"predicate must be a mapping, got {pred!r}")
    for combinator in ("all", "any"):
        if combinator in pred:
            for p in pred[combinator]:
                check(p)
            return
    if "not" in pred:
        check(pred["not"])
        return
    if pred.get("op") not in OPS or not isinstance(pred.get("path"), str):
        raise SchemaError(f"bad predicate {pred!r}: needs a path and one of {sorted(OPS)}")


def evaluate(pred: dict, state: dict) -> bool:
    check(pred)
    if "all" in pred:
        return all(evaluate(p, state) for p in pred["all"])
    if "any" in pred:
        return any(evaluate(p, state) for p in pred["any"])
    if "not" in pred:
        return not evaluate(pred["not"], state)
    return bool(OPS[pred["op"]](resolve(state, pred["path"]), pred.get("value")))
