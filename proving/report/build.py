"""Assemble the report for one comparison: frozen configuration, bar, results, cost, calibration, verdict.

The JSON is the record. The Markdown view is printed on demand and never committed.
"""

from __future__ import annotations

from . import compare, enterprise


def build(client: str, baseline: str, candidate: str, configs: dict, deployment: dict, hypotheses: list[dict],
          runs_a: list[dict], runs_b: list[dict], judges: dict | None = None) -> dict:
    bar = enterprise.evidence_bar(deployment["autonomy"], deployment["consequence"])
    base, cand = compare.summarise(runs_a), compare.summarise(runs_b)
    deltas = compare.deltas(runs_a, runs_b, bar["confidence"])
    hyps = [compare.hypothesis(h, runs_a, runs_b, bar["confidence"]) for h in hypotheses]
    gate = enterprise.gate(bar, base, cand, deltas, hyps)
    calibration = (judges or {}).get("calibration") or {"status": "not run",
                                                       "note": "no probabilistic score was produced offline"}
    return {
        "client": client, "baseline": baseline, "candidate": candidate,
        "configuration": configs,
        "deployment": {
            **deployment,
            "autonomy_text": enterprise.AUTONOMY[deployment["autonomy"]][0],
            "consequence_text": enterprise.CONSEQUENCE[deployment["consequence"]][0],
        },
        "evidence_bar": bar,
        "scenarios": {"total": len(runs_b), "adversarial": sum(1 for r in runs_b if r["adversarial"])},
        "hypotheses": hyps,
        "baseline_summary": base,
        "candidate_summary": cand,
        "deltas": deltas,
        "calibration": calibration,
        "judges": (judges or {}).get("judges") or {"status": "not run"},
        "gates": gate["gates"],
        "verdict": gate["verdict"],
        "verdict_line": verdict_line(gate, hyps),
    }


def verdict_line(gate: dict, hyps: list[dict]) -> str:
    failing = [g for g in gate["gates"] if not g["passed"]]
    if not failing:
        return f"{gate['verdict']}: every gate passed"
    names = ", ".join(g["gate"] for g in failing)
    return f"{gate['verdict']}: {names} did not pass"


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def to_markdown(r: dict) -> str:
    lines = [f"# {r['client']}: {r['baseline']} vs {r['candidate']}", "",
             f"**Verdict: {r['verdict']}.** {r['verdict_line']}", "",
             "## Configuration under test", ""]
    for side in ("baseline", "candidate"):
        c = r["configuration"][side]
        lines.append(f"- {side} `{c['version']}`: client {c['client_repo']} at `{c['client_sha'][:12]}`, "
                     f"models {c['model_ids'] or 'none'}, hashes " +
                     ", ".join(f"{k} `{v}`" for k, v in c["hashes"].items()))
    d, bar = r["deployment"], r["evidence_bar"]
    lines += ["", "## Evidence bar", "",
              f"Autonomy {d['autonomy']} ({d['autonomy_text']}), consequence {d['consequence']} "
              f"({d['consequence_text']}): tier {bar['tier']}, {bar['confidence']:.0%} confidence, at least "
              f"{bar['min_scenarios']} scenarios, hazard rate at most {bar['max_hazard_rate']}, task success may "
              f"not drop more than {bar['success_margin']}.", "", "## Hypotheses", ""]
    for h in r["hypotheses"]:
        lines.append(f"- **{h['id']}** ({h['verdict']}): {h['claim']} {h['metric']} {h['baseline_mean']} -> "
                     f"{h['candidate_mean']} over {h['n']} scenarios, improvement {h['improvement']} "
                     f"({h['ci'][0]} to {h['ci'][1]}, {h['level']:.0%}).")
    b, c = r["baseline_summary"], r["candidate_summary"]
    lines += ["", "## Results", "", "| | baseline | candidate |", "|---|---|---|",
              f"| task success | {_pct(b['success_rate'])} | {_pct(c['success_rate'])} |",
              f"| runs with a hazard | {b['hazard_runs']} | {c['hazard_runs']} |",
              f"| abandoned | {b['abandoned']} | {c['abandoned']} |",
              f"| turns per run | {b['mean_turns']} | {c['mean_turns']} |",
              f"| turn latency p50 / p95 ms | {b['latency_ms']['p50']} / {b['latency_ms']['p95']} | "
              f"{c['latency_ms']['p50']} / {c['latency_ms']['p95']} |",
              f"| model tokens per run | {b['tokens']['per_run']} | {c['tokens']['per_run']} |",
              "", "## Gates", ""]
    lines += [f"- {g['gate']}: {g['outcome']}. {g['detail']}" for g in r["gates"]]
    lines += ["", "## Calibration", "", str(r["calibration"].get("status", "reported in the JSON"))]
    return "\n".join(lines) + "\n"
