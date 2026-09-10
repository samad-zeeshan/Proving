"""Run the judges on a sample of transcripts and measure them against the tool-state labels.

Model verdicts are cached by transcript hash and committed, so CI rebuilds the same numbers offline.
"""

from __future__ import annotations

import hashlib
from statistics import fmean

from .. import llm
from ..scoring import judge

MODEL_JUDGES = ("pointwise", "sceptical")


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def sample(runs_by_version: dict[str, list[dict]], per_version: int) -> list[tuple[str, dict]]:
    """Up to half failures and the rest successes per version, in a fixed hash order.

    Successes outnumber failures ten to one, so a plain random sample would teach calibration very
    little about the calls that went wrong.
    """
    picked = []
    for version, runs in sorted(runs_by_version.items()):
        valid = sorted((r for r in runs if r["outcome"]["valid"]), key=lambda r: _h(version + r["scenario"]))
        fails = [r for r in valid if not r["outcome"]["success"]][: per_version // 2]
        wins = [r for r in valid if r["outcome"]["success"]][: per_version - len(fails)]
        picked += [(version, r) for r in fails + wins]
    return picked


def verdicts(items: list[tuple[str, dict]], cache: dict, use_model: bool) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"heuristic": []}
    for name in MODEL_JUDGES:
        out[name] = []
    missing = 0
    for _, run in items:
        text = judge.transcript_text(run)
        out["heuristic"].append(judge.heuristic(text))
        for name in MODEL_JUDGES:
            k = judge.key(name, text)
            if k not in cache:
                if not use_model:
                    missing += 1
                    continue
                cache[k] = judge.model_judge(name, text)
            out[name].append(cache[k])
    if missing:
        raise llm.ModelUnavailable(f"{missing} judge verdicts are not cached; set PROVING_LLM=1 to make them")
    return out


def evaluate(items: list[tuple[str, dict]], preds: dict[str, list[dict]], model: str) -> dict:
    ys = [int(bool(r["outcome"]["success"])) for _, r in items]
    # Anchors fit the calibration map, the rest measure it. The split is by hash, never by outcome.
    anchor = [_h(v + r["scenario"] + "anchor") % 10 < 4 for v, r in items]
    test = [not a for a in anchor]

    def part(values, mask):
        return [v for v, m in zip(values, mask) if m]

    judges, calibrated = {}, {}
    for name, rows in preds.items():
        ps = [row["p"] for row in rows]
        ab = judge.fit_platt(part(ps, anchor), part(ys, anchor))
        cal = [judge.apply_platt(p, ab) for p in ps]
        calibrated[name] = part(cal, test)
        raw_rel = judge.reliability(part(ps, test), part(ys, test))
        cal_rel = judge.reliability(part(cal, test), part(ys, test))
        judges[name] = {
            "model": None if name == "heuristic" else model,
            "platt": list(ab), "anchors": sum(anchor), "held_out": sum(test),
            "accuracy_raw": judge.accuracy(part(ps, test), part(ys, test)),
            "accuracy_calibrated": judge.accuracy(part(cal, test), part(ys, test)),
            "ece_raw": raw_rel["ece"], "ece_calibrated": cal_rel["ece"],
            "reliability_raw": raw_rel["bins"], "reliability_calibrated": cal_rel["bins"],
            "unparsed": sum(1 for row in rows if row.get("unparsed")),
            "tokens": sum((row.get("usage") or {}).get("total_tokens", 0) for row in rows),
        }
    help_by_version: dict[str, dict] = {}
    for name in MODEL_JUDGES:
        for (version, _), row in zip(items, preds[name]):
            if row.get("helpfulness"):
                help_by_version.setdefault(name, {}).setdefault(version, []).append(row["helpfulness"])
    ys_test = part(ys, test)
    return {
        "calibration": {
            "status": "run", "label": "task success from the final tool state",
            "scores": [{"name": f"judge:{n}", "ece_raw": j["ece_raw"], "ece_calibrated": j["ece_calibrated"],
                        "held_out": j["held_out"]} for n, j in judges.items()],
        },
        "judges": {
            "sample": {"transcripts": len(items), "successes": sum(ys),
                       "by_version": {v: sum(1 for x, _ in items if x == v) for v in sorted({v for v, _ in items})}},
            "per_judge": judges,
            "cascade": judge.cascade(calibrated["heuristic"], calibrated["pointwise"], ys_test),
            "correlation": judge.error_correlation(calibrated, ys_test),
            "helpfulness": {n: {v: round(fmean(xs), 3) for v, xs in sorted(d.items())}
                            for n, d in help_by_version.items()},
        },
    }
