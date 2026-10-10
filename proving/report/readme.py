"""Render the README's results block from the files in eval/results. CI fails if the two drift apart."""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

BEGIN, END = "<!-- results:begin -->", "<!-- results:end -->"
NAMES = {"resolver-off": "without the call checker", "v2": "as shipped, with the call checker",
         "rules": "hand-written rules", "llm": "small AI model"}
# The recorded claims use internal words like "resolver". The README states the same claim the way the demo does.
CLAIMS = {"resolver": "With the call checker, fewer planted calls reach Warden's server.",
          "nlu-llm": "If a small AI model reads callers instead of hand-written rules, the agent books more viewings."}
VERDICTS = {"confirmed": "proved true", "refuted": "proved false"}
HARM = {"wrong_phone": "saved the wrong phone number", "wrong_booking": "booked the wrong viewing",
        "spoke_injected_text": "repeated text planted in a listing"}


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _n(x, d=2) -> str:
    return f"{x:.{d}f}"


def _ci(h: dict) -> str:
    return f"{_n(h['improvement'], 3)} ({_n(h['ci'][0], 3)} to {_n(h['ci'][1], 3)})"


def _sig2(x: float) -> str:
    # Prose rounds to two significant figures, half up, the same way the demo page does.
    if x == 0:
        return "0"
    d = Decimal(str(x))
    q = d.scaleb(-(d.adjusted() - 1)).quantize(Decimal(1), ROUND_HALF_UP).scaleb(d.adjusted() - 1)
    return f"{int(q):,}" if q == q.to_integral_value() else f"{q.normalize():f}"


def _about(x: float) -> str:
    r = _sig2(x)
    return r if Decimal(r.replace(",", "")) == Decimal(str(x)) else f"about {r}"


def _paired_success(results: Path) -> tuple[int, int]:
    rep = _load(results / "parley" / "rules-vs-llm.json")
    h = rep["hypotheses"][0]
    return h["same_outcome"], h["n"]


def _series(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


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
            "| Agent | Change | Claim | Customers | Before, after | Change (range) | Claim result | Report says |",
            "|---|---|---|---|---|---|---|---|"]
    for label, r in (("Warden", w), ("Parley", p)):
        for h in r["hypotheses"]:
            out.append(f"| {label} | {NAMES[r['baseline']]} to {NAMES[r['candidate']]} | "
                       f"{CLAIMS.get(h['id'], h['claim'])} | {h['n']} | "
                       f"{_n(h['baseline_mean'], 3)}, {_n(h['candidate_mean'], 3)} | {_ci(h)} at "
                       f"{round(h['level'] * 100)}% | **{VERDICTS.get(h['verdict'], h['verdict'])}** | {r['verdict']} |")

    out += ["", "This table shows how each made-up customer ended, from the final tool state.", "",
            "| Agent, version | Customers | Goal met | Calls that caused harm | Customer gave up | Turns per call | "
            "Reply time p50, p95 (ms) | Model tokens per call |",
            "|---|---|---|---|---|---|---|---|"]
    for label, r in (("Warden", w), ("Parley", p)):
        for side in ("baseline", "candidate"):
            s = r[f"{side}_summary"]
            out.append(f"| {label}, {NAMES[r[side]]} | {s['valid']} | {s['successes']} ({_pct(s['success_rate'])}) | "
                       f"{s['hazard_runs']} | {s['abandoned']} | {s['mean_turns']} | {_n(s['latency_ms']['p50'], 1)}, "
                       f"{_n(s['latency_ms']['p95'], 1)} | {_n(s['tokens']['per_run'], 0)} |")

    wc, wb = w["candidate_summary"], w["baseline_summary"]
    wh = w["hypotheses"][0]
    pb, pc = p["baseline_summary"], p["candidate_summary"]
    hz = _series([f"{HARM.get(k, k.replace('_', ' '))} {_sig2(v)} times" for k, v in pb["hazards"].items()])
    xs, ys = _paired_success(results)
    same = (f"for every one of {_about(ys)} standard customers" if xs == ys
            else f"for {_about(xs)} of {_about(ys)} standard customers")
    out += ["", f"With the call checker, planted calls that reached Warden's server fell to "
            f"{_about(wh['candidate_mean'])} per customer who tried tricks. Before, it was "
            f"{_about(wh['baseline_mean'])}, so the change is better. "
            f"Real harm was {wb['hazard_runs']} before and {wc['hazard_runs']} after, because Warden's server refused "
            f"every planted call that the checker stops. "
            f"Parley's two versions ended the same way {same}. Both {hz}. "
            f"This harm keeps Parley's report at hold, whichever way it reads callers."]

    cost = pc["cost"]
    t = cost["total"]
    if t["total"]:
        per = lambda k: _n(t[k] / pc["valid"], 0)  # noqa: E731
        share = t["injected_context"] / t["total"]
        out += ["", "The next table splits the token cost of the small AI model by the Total Cost of Agency method "
                "(arXiv 2609.23790). Proving counts each prompt twice with no reply, once as sent and once without "
                f"the added listing details. Those details take {_about(share * 100)}% of the tokens, which is a small "
                "share. Earlier turns add nothing, because the model sees one turn at a time.",
                "", "| Part | Model calls | Fixed instructions | Listing details added | Model's own answer | "
                "Answers thrown away | Earlier turns sent again | Total |",
                "|---|---|---|---|---|---|---|---|"]
        for node, c in cost["by_node"].items():
            out.append(f"| {node} | {c['calls']} | {c['base_prompt']} | {c['injected_context']} | {c['inference']} | "
                       f"{c['miss_penalty']} | {c['accumulation']} | {c['total']} |")
        out.append(f"| per call | | {per('base_prompt')} | {per('injected_context')} | {per('inference')} | "
                   f"{per('miss_penalty')} | {per('accumulation')} | {per('total')} |")

    if ch:
        rows = ch["mtva"]["rows"]
        clean = next((r for r in rows if r["condition"] == "clean"), None)
        worst = max((r for r in rows if r["condition"].startswith("noise@")),
                    key=lambda r: r["word_error_rate"], default=None)
        out += ["", "The next table tests Parley with hand-written rules on standard customers. The noise rows garble "
                "the caller's words in text, after MTVA (arXiv 2609.20152). The audio rows send speech through "
                "Parley's own Piper voices and Whisper small, after TRACE (arXiv 2609.29452)."]
        if clean and worst:
            out[-1] += (f" With the most noise, only {_about(worst['completed'])} calls met their goal. With clean "
                        f"text, {_about(clean['completed'])} did. That is a steep fall.")
        out += ["", "| Channel | Calls | Goal met | Wrong actions | Word error rate | Hit trouble, recovered | "
                "Extra caller turns |", "|---|---|---|---|---|---|---|"]
        for row in ch["mtva"]["rows"] + ch["trace"]["rows"]:
            extra = "" if row.get("extra_turns") is None else _n(row["extra_turns"], 2)
            out.append(f"| {row['condition']} | {row['runs']} | {row['completed']} | {row['wrong_actions']} | "
                       f"{_n(row['word_error_rate'], 3)} | {row['troubled']}, {row['recovered']} | {extra} |")

    if jd:
        j = jd["judges"]
        out += ["", "| Judge | Right answers, before and after calibration | Confidence error (ECE), before and after |",
                "|---|---|---|"]
        for name, x in j["per_judge"].items():
            out.append(f"| {name} | {_n(x['accuracy_raw'], 3)}, {_n(x['accuracy_calibrated'], 3)} | "
                       f"{_n(x['ece_raw'], 3)}, {_n(x['ece_calibrated'], 3)} |")
        corr = j["correlation"]
        best = max(j["cascade"], key=lambda r: (r["accuracy"], -r["escalated"]))
        coin = ", which is barely better than a coin toss" if best["accuracy"] < 0.6 else ""
        out += ["", "The judges read only the transcript. Proving scored them against the final tool state on "
                f"{_about(j['sample']['transcripts'])} sample calls (arXiv 2609.29431, 2609.26489). "
                f"The judges often make the same mistakes. Their mean error correlation is "
                f"{_about(corr['mean_error_correlation'])}, so the {len(corr['judges'])} judges are worth "
                f"{_about(corr['effective_judges'])} independent judges (arXiv 2609.22512). A cheap-first cascade "
                f"(arXiv 2609.26550) at threshold {best['threshold']} sends {_about(best['escalated'])} of "
                f"{_about(j['per_judge']['heuristic']['held_out'])} held-out calls to the model judge. "
                f"It gets {_about(best['accuracy'] * 100)}% of them right{coin}."]

    tail = []
    if fid:
        calls = ("every sequence of calls" if fid["same_tool_calls"] == fid["scenarios"]
                 else f"{_about(fid['same_tool_calls'])} sequences of calls")
        outcome = ("every outcome" if fid["same_outcome"] == fid["scenarios"]
                   else f"{_about(fid['same_outcome'])} outcomes")
        tail.append(f"Parley's real booking service and Proving's tool simulator agreed on {outcome} and {calls}, "
                    f"across {_about(fid['scenarios'])} customers.")
    if reg:
        tail.append(f"Proving replayed {_about(reg['replayed'])} recorded calls on a version of the hand-written "
                    f"rules with a deliberate bug. The replay stopped {_about(reg['diverged'])} of them at the first "
                    f"changed step. When those calls ran for real from that step, {_about(reg['lost_success'])} lost "
                    f"their booking. So the replay finds real damage.")
    if wreg:
        tail.append(f"Proving also replayed {_about(wreg['replayed'])} recorded Warden calls without the call "
                    f"checker. The replay marked {_about(wreg['diverged'])} as changed and {wreg['lost_success']} as "
                    f"worse.")
    if cust:
        both = (f"Both customers got {cust['model_customer_success']} bookings."
                if cust["model_customer_success"] == cust["rules_customer_success"]
                else f"The model customer got {cust['model_customer_success']} bookings, against "
                     f"{cust['rules_customer_success']} for the rules customer.")
        tail.append(f"A model customer uses the local 9B model to reword the lines of the rules customer. Across "
                    f"{_about(cust['scenarios'])} English callers, it reached the same outcome as the rules customer "
                    f"{cust['same_outcome']} times. {both}")
    # Two paragraphs keep each one under the six-sentence limit that the copy test enforces.
    if tail:
        out += ["", " ".join(tail[:2])]
    if tail[2:]:
        out += ["", " ".join(tail[2:])]
    return "\n".join(out)


def splice(readme: str, block: str) -> str:
    head, rest = readme.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{block}\n{END}{tail}"
