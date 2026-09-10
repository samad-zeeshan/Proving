"""Judges that read only the transcript, calibrated against what the tool state says happened.

The label for "did the customer get what they came for" comes from the booking backend, so every
transcript is a trusted example. That makes calibration (arXiv 2609.29431, 2609.26489), the cheap-first
cascade (arXiv 2609.26550) and error correlation between judges (arXiv 2609.22512) measurable.
"""

from __future__ import annotations

import hashlib
import math
import re
from statistics import fmean

from .. import llm

RUBRIC = {
    "pointwise": ("You grade a recorded phone call between a booking agent and a customer. Decide from the "
                  "transcript alone whether the customer ended the call with the viewing they asked for "
                  "booked, on the terms they gave. Also rate how helpful the agent was from 1 to 5."),
    "sceptical": ("You audit phone calls for a property agency. Assume nothing was booked unless the agent "
                  "clearly confirmed a booking that matches everything the customer asked for, including "
                  "the phone number they gave. Rate the agent's helpfulness from 1 to 5."),
}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["success", "confidence", "helpfulness"],
    "properties": {"success": {"type": "boolean"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                   "helpfulness": {"type": "integer", "minimum": 1, "maximum": 5}},
}
_BOOKED = re.compile(r"is booked|booking is confirmed|تم الحجز", re.I)


def transcript_text(run: dict) -> str:
    lines = []
    for t in run["turns"]:
        if t.get("customer"):
            lines.append(f"Customer: {t['customer']}")
        if t.get("agent"):
            lines.append(f"Agent: {t['agent']}")
    return "\n".join(lines)


def key(judge: str, text: str) -> str:
    return hashlib.sha256(f"{judge}\n{text}".encode()).hexdigest()[:20]


def heuristic(text: str) -> dict:
    """The cheap first judge: did the agent say the words of a confirmed booking, and who hung up."""
    agent_lines = [ln for ln in text.splitlines() if ln.startswith("Agent:")]
    last = agent_lines[-1] if agent_lines else ""
    if _BOOKED.search(last):
        p = 0.85
    elif any(_BOOKED.search(ln) for ln in agent_lines):
        p = 0.6
    else:
        p = 0.1
    return {"p": p, "helpfulness": None}


def model_judge(variant: str, text: str) -> dict:
    out = llm.chat([{"role": "system", "content": RUBRIC[variant]}, {"role": "user", "content": text}],
                   schema=SCHEMA, max_tokens=80)
    try:
        data = llm.parse_json(out["content"])
        conf = min(1.0, max(0.0, float(data["confidence"])))
        p = conf if data["success"] else 1 - conf
        return {"p": round(p, 4), "helpfulness": int(data["helpfulness"]), "usage": out["usage"]}
    except (ValueError, KeyError, TypeError):
        return {"p": 0.5, "helpfulness": None, "usage": out["usage"], "unparsed": True}


# ---------------------------------------------------------------------------
# Calibration, cascade and error dependence
# ---------------------------------------------------------------------------

def _logit(p: float) -> float:
    p = min(1 - 1e-4, max(1e-4, p))
    return math.log(p / (1 - p))


def fit_platt(ps: list[float], ys: list[int], steps: int = 2000, lr: float = 0.05) -> tuple[float, float]:
    """Fit sigmoid(a * logit(p) + b) to the labels by gradient descent. Two numbers, no library."""
    a, b = 1.0, 0.0
    xs = [_logit(p) for p in ps]
    for _ in range(steps):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            q = 1 / (1 + math.exp(-(a * x + b)))
            ga += (q - y) * x
            gb += q - y
        a -= lr * ga / len(xs)
        b -= lr * gb / len(xs)
    return round(a, 4), round(b, 4)


def apply_platt(p: float, ab: tuple[float, float]) -> float:
    return 1 / (1 + math.exp(-(ab[0] * _logit(p) + ab[1])))


def reliability(ps: list[float], ys: list[int], bins: int = 10) -> dict:
    rows = []
    ece = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [k for k, p in enumerate(ps) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not idx:
            continue
        conf = fmean(ps[k] for k in idx)
        acc = fmean(ys[k] for k in idx)
        ece += len(idx) / len(ps) * abs(conf - acc)
        rows.append({"bin": [lo, hi], "n": len(idx), "confidence": round(conf, 4), "accuracy": round(acc, 4)})
    return {"ece": round(ece, 4), "bins": rows}


def accuracy(ps: list[float], ys: list[int]) -> float:
    return round(fmean(int((p >= 0.5) == bool(y)) for p, y in zip(ps, ys)), 4)


def error_correlation(preds: dict[str, list[float]], ys: list[int]) -> dict:
    names = sorted(preds)
    errs = {n: [int((p >= 0.5) != bool(y)) for p, y in zip(preds[n], ys)] for n in names}

    def corr(u, v):
        mu, mv = fmean(u), fmean(v)
        su = math.sqrt(fmean((x - mu) ** 2 for x in u))
        sv = math.sqrt(fmean((x - mv) ** 2 for x in v))
        if su == 0 or sv == 0:
            return None
        return fmean((x - mu) * (y - mv) for x, y in zip(u, v)) / (su * sv)

    pairs = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            c = corr(errs[a], errs[b])
            pairs[f"{a}|{b}"] = None if c is None else round(c, 4)
    known = [c for c in pairs.values() if c is not None]
    rho = fmean(known) if known else 0.0
    k = len(names)
    # With k judges whose errors correlate at rho on average, their agreement carries the information
    # of k / (1 + (k - 1) rho) independent judges (the design effect used in arXiv 2609.22512).
    n_eff = k / (1 + (k - 1) * rho) if k else 0
    return {"judges": names, "pairwise": pairs, "mean_error_correlation": round(rho, 4),
            "effective_judges": round(n_eff, 2), "error_rates": {n: round(fmean(errs[n]), 4) for n in names}}


def cascade(cheap: list[float], strong: list[float], ys: list[int], thresholds=(0.6, 0.7, 0.8, 0.9, 0.95)) -> list:
    rows = []
    for tau in thresholds:
        escalated = [max(c, 1 - c) < tau for c in cheap]
        final = [s if e else c for c, s, e in zip(cheap, strong, escalated)]
        rows.append({"threshold": tau, "escalated": sum(escalated), "share_escalated": round(fmean(escalated), 4),
                     "accuracy": accuracy(final, ys)})
    return rows
