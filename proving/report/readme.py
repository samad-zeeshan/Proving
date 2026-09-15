"""Render the README's results block from the files in eval/results. CI fails if the two drift apart."""

from __future__ import annotations

import json
from pathlib import Path

BEGIN, END = "<!-- results:begin -->", "<!-- results:end -->"
NAMES = {"resolver-off": "resolver off", "v2": "Warden as shipped", "rules": "rule parser", "llm": "9B model parser"}


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _n(x, d=2) -> str:
    return f"{x:.{d}f}"


def _ci(h: dict) -> str:
    return f"{_n(h['improvement'], 3)} ({_n(h['ci'][0], 3)} to {_n(h['ci'][1], 3)})"


def _paired_success(results: Path) -> tuple[int, int]:
    rep = _load(results / "parley" / "rules-vs-llm.json")
    h = rep["hypotheses"][0]
    return h["same_outcome"], h["n"]


def render(results: Path) -> str:
    w = _load(results / "warden" / "resolver-off-vs-v2.json")
    p = _load(results / "parley" / "rules-vs-llm.json")
    ch = _load(results / "parley" / "channels.json")
    jd = _load(results / "parley" / "judges.json")
    fid = _load(results / "parley" / "fidelity.json")
    reg = _load(results / "parley" / "regression-rules-regressed.json")
    wreg = _load(results / "warden" / "regression-resolver-off.json")
    cust = _load(results / "parley" / "customers.json")
    out = []

    out += [
            "| Agent | Change | Hypothesis | Scenarios | Before, after | Improvement (interval) | Verdict | Report says |",
            "|---|---|---|---|---|---|---|---|"]
    for label, r in (("Warden", w), ("Parley", p)):
        for h in r["hypotheses"]:
            out.append(f"| {label} | {NAMES[r['baseline']]} to {NAMES[r['candidate']]} | {h['claim']} | {h['n']} | "
                       f"{_n(h['baseline_mean'], 3)}, {_n(h['candidate_mean'], 3)} | {_ci(h)} at "
                       f"{round(h['level'] * 100)}% | **{h['verdict']}** | {r['verdict']} |")

    out += ["", "What each simulated customer ended with, from the final tool state:", "",
            "| Agent, version | Customers | Goal met | Calls with a hazard | Customer gave up | Turns per call | "
            "Turn p50, p95 (ms) | Model tokens per call |",
            "|---|---|---|---|---|---|---|---|"]
    for label, r in (("Warden", w), ("Parley", p)):
        for side in ("baseline", "candidate"):
            s = r[f"{side}_summary"]
            out.append(f"| {label}, {NAMES[r[side]]} | {s['valid']} | {s['successes']} ({_pct(s['success_rate'])}) | "
                       f"{s['hazard_runs']} | {s['abandoned']} | {s['mean_turns']} | {_n(s['latency_ms']['p50'], 1)}, "
                       f"{_n(s['latency_ms']['p95'], 1)} | {_n(s['tokens']['per_run'], 0)} |")

    wc, wb = w["candidate_summary"], w["baseline_summary"]
    pb, pc = p["baseline_summary"], p["candidate_summary"]
    hz = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in pb["hazards"].items())
    xs, ys = _paired_success(results)
    out += ["", f"Intervals are paired bootstrap intervals at the confidence each agent's evidence bar asks for. "
            f"Warden's planted calls reaching its server fell from {_n(w['hypotheses'][0]['baseline_mean'], 3)} to "
            f"{_n(w['hypotheses'][0]['candidate_mean'], 3)} per adversarial scenario, while hazards that actually "
            f"happened stayed at {wb['hazard_runs']} and {wc['hazard_runs']}: the server refused every planted call "
            f"the resolver would have. Parley's two parsers reached the same outcome on {xs} of {ys} standard "
            f"scenarios. Parley's hazards, identical in both versions, by kind: {hz}. They keep its report at hold "
            f"whatever the parser."]

    cost = pc["cost"]
    t = cost["total"]
    if t["total"]:
        per = lambda k: _n(t[k] / pc["valid"], 0)  # noqa: E731
        share = t["injected_context"] / t["total"]
        out += ["", f"Token cost of the 9B parser, split the Total Cost of Agency way (arXiv 2609.23790) and counted "
                f"twice without generating, once as sent and once with the injected context taken out. Injected context "
                f"is {_pct(share)} of the tokens, and accumulation is zero because the parser sees one turn at a time.",
                "", "| Node | Model calls | Base prompt | Injected context | Inference | Miss penalty | Accumulation | Total |",
                "|---|---|---|---|---|---|---|---|"]
        for node, c in cost["by_node"].items():
            out.append(f"| {node} | {c['calls']} | {c['base_prompt']} | {c['injected_context']} | {c['inference']} | "
                       f"{c['miss_penalty']} | {c['accumulation']} | {c['total']} |")
        out.append(f"| per call | | {per('base_prompt')} | {per('injected_context')} | {per('inference')} | "
                   f"{per('miss_penalty')} | {per('accumulation')} | {per('total')} |")

    if ch:
        out += ["", "Parley under transcript noise (MTVA style, arXiv 2609.20152), rule parser, standard scenarios, "
                "and under acoustic stress (TRACE style, arXiv 2609.29452) through Parley's own Piper voices and "
                "Whisper small:", "",
                "| Channel | Calls | Goal met | Wrong actions | Word error rate | Hit trouble, recovered | "
                "Extra caller turns |", "|---|---|---|---|---|---|---|"]
        for row in ch["mtva"]["rows"] + ch["trace"]["rows"]:
            extra = "" if row.get("extra_turns") is None else _n(row["extra_turns"], 2)
            out.append(f"| {row['condition']} | {row['runs']} | {row['completed']} | {row['wrong_actions']} | "
                       f"{_n(row['word_error_rate'], 3)} | {row['troubled']}, {row['recovered']} | {extra} |")

    if jd:
        j = jd["judges"]
        out += ["", f"Judges read only the transcript and were scored against the tool state on {j['sample']['transcripts']} "
                f"sampled calls, calibrated on anchors and measured on the rest (arXiv 2609.29431, 2609.26489):", "",
                "| Judge | Accuracy raw, calibrated | ECE raw, calibrated |", "|---|---|---|"]
        for name, x in j["per_judge"].items():
            out.append(f"| {name} | {_n(x['accuracy_raw'], 3)}, {_n(x['accuracy_calibrated'], 3)} | "
                       f"{_n(x['ece_raw'], 3)}, {_n(x['ece_calibrated'], 3)} |")
        corr = j["correlation"]
        best = max(j["cascade"], key=lambda r: (r["accuracy"], -r["escalated"]))
        out += ["", f"Mean error correlation between the judges is {_n(corr['mean_error_correlation'], 3)}, so the "
                f"{len(corr['judges'])} judges carry the evidence of {_n(corr['effective_judges'], 2)} independent ones "
                f"(arXiv 2609.22512). The cheap-first cascade (arXiv 2609.26550) at threshold {best['threshold']} sends "
                f"{best['escalated']} of {j['per_judge']['heuristic']['held_out']} held-out calls to the model judge and "
                f"scores {_n(best['accuracy'], 3)}."]

    tail = []
    if fid:
        tail.append(f"The tool synthesizer and Parley's real booking service agreed on {fid['same_outcome']} of "
                    f"{fid['scenarios']} outcomes and {fid['same_tool_calls']} call sequences.")
    if reg:
        tail.append(f"Replaying the {reg['replayed']} recorded rule-parser calls against a deliberately broken build "
                    f"stopped {reg['diverged']} of them at the first changed step; run on live from there, "
                    f"{reg['lost_success']} lost their booking.")
    if wreg:
        tail.append(f"Replaying Warden's {wreg['replayed']} recorded runs without the resolver flagged {wreg['diverged']} "
                    f"as changed and {wreg['lost_success']} as worse.")
    if cust:
        tail.append(f"On {cust['scenarios']} English callers, the model customer (the local 9B model rewording the "
                    f"rules customer's lines) reached the same outcome as the rules customer {cust['same_outcome']} "
                    f"times: {cust['model_customer_success']} bookings against {cust['rules_customer_success']}.")
    if tail:
        out += ["", " ".join(tail)]
    return "\n".join(out)


def splice(readme: str, block: str) -> str:
    head, rest = readme.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{block}\n{END}{tail}"
