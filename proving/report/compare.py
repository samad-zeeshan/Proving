"""Compare two versions over the same scenarios: per-hypothesis deltas and the headline numbers."""

from __future__ import annotations

from statistics import fmean

from ..scenarios.predicates import _MISSING, resolve
from ..scoring import cost, stats


def metric_value(run: dict, metric: str) -> float | None:
    o = run["outcome"]
    if not o["valid"]:
        return None
    if metric == "success":
        return 1.0 if o["success"] else 0.0
    if metric == "hazard":
        return 1.0 if o["hazards"] else 0.0
    if metric == "turns":
        return float(o["agent_turns"])
    if metric == "tokens":
        return float(o["cost"]["total"]["total"])
    v = resolve(run["final_state"], metric)
    if v is _MISSING or v is None:
        return None
    return float(v)


def select(runs: list[dict], which: str) -> list[dict]:
    if which == "all":
        return runs
    if which == "adversarial":
        return [r for r in runs if r["adversarial"]]
    if which == "standard":
        return [r for r in runs if not r["adversarial"]]
    return [r for r in runs if r["hypothesis"] == which or r["template"] == which]


def paired(a: list[dict], b: list[dict], metric: str, which: str = "all") -> tuple[list[float], list[float], int]:
    by_id = {r["scenario"]: r for r in b}
    xs, ys, excluded = [], [], 0
    for ra in select(a, which):
        rb = by_id.get(ra["scenario"])
        x = metric_value(ra, metric)
        y = metric_value(rb, metric) if rb else None
        if x is None or y is None:
            excluded += 1
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys, excluded


def hypothesis(spec: dict, a: list[dict], b: list[dict], level: float) -> dict:
    xs, ys, excluded = paired(a, b, spec["metric"], spec.get("set", "all"))
    boot = stats.bootstrap_delta(xs, ys, level=level)
    if spec["direction"] == "increase":
        imp, lo, hi = boot["delta"], boot["lo"], boot["hi"]
    else:
        imp = None if boot["delta"] is None else -boot["delta"]
        lo = None if boot["hi"] is None else -boot["hi"]
        hi = None if boot["lo"] is None else -boot["lo"]
    return {
        "id": spec["id"], "claim": spec["claim"], "metric": spec["metric"], "direction": spec["direction"],
        "min_effect": spec["min_effect"], "set": spec.get("set", "all"), "n": len(xs), "excluded": excluded,
        "baseline_mean": round(fmean(xs), 4) if xs else None,
        "candidate_mean": round(fmean(ys), 4) if ys else None,
        "delta": boot["delta"], "improvement": imp, "ci": [lo, hi], "level": level,
        "verdict": stats.verdict(lo, hi, spec["min_effect"]) if xs else "underpowered",
    }


def summarise(runs: list[dict]) -> dict:
    valid = [r for r in runs if r["outcome"]["valid"]]
    latencies = [ms for r in valid for ms in r["outcome"]["latency_ms"]]
    hazards: dict[str, int] = {}
    for r in valid:
        for h in r["outcome"]["hazards"]:
            hazards[h] = hazards.get(h, 0) + 1
    tca = cost.merge([r["outcome"]["cost"] for r in valid])
    n = len(valid) or 1
    return {
        "runs": len(runs), "valid": len(valid), "diverged": len(runs) - len(valid),
        "successes": sum(1 for r in valid if r["outcome"]["success"]),
        "success_rate": round(sum(1 for r in valid if r["outcome"]["success"]) / n, 4),
        "hazard_runs": sum(1 for r in valid if r["outcome"]["hazards"]),
        "hazards": dict(sorted(hazards.items())),
        "abandoned": sum(1 for r in valid if r["outcome"]["abandoned"]),
        "mean_turns": round(fmean(r["outcome"]["agent_turns"] for r in valid), 2) if valid else None,
        "latency_ms": {"p50": stats.percentile(latencies, 0.5), "p95": stats.percentile(latencies, 0.95),
                       "turns": len(latencies)},
        "tool_calls_per_run": round(sum(r["outcome"]["tool_calls"] for r in valid) / n, 2),
        "tool_errors": sum(r["outcome"]["tool_errors"] for r in valid),
        "model_calls": sum(r["outcome"]["model_calls"] for r in valid),
        "tokens": {"total": tca["total"]["total"], "per_run": round(tca["total"]["total"] / n, 1)},
        "cost": tca,
    }


def deltas(a: list[dict], b: list[dict], level: float) -> dict:
    out = {}
    for metric in ("success", "hazard"):
        xs, ys, excluded = paired(a, b, metric)
        out[metric] = {**stats.bootstrap_delta(xs, ys, level=level), "excluded": excluded}
    return out
