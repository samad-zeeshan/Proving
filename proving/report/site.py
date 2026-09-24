"""Pack recorded runs and reports into the small JSON files the static demo replays."""

from __future__ import annotations

TILES_STANDARD, TILES_ADVERSARIAL = 36, 12
TEXT = 260


def _round_robin(runs: list[dict], n: int) -> list[str]:
    groups: dict[str, list[str]] = {}
    for r in sorted(runs, key=lambda r: r["scenario"]):
        groups.setdefault(r["template"], []).append(r["scenario"])
    out, rank = [], 0
    while len(out) < n and any(rank < len(g) for g in groups.values()):
        for g in groups.values():
            if rank < len(g) and len(out) < n:
                out.append(g[rank])
        rank += 1
    return out


def pick(runs: list[dict]) -> list[str]:
    return (_round_robin([r for r in runs if not r["adversarial"]], TILES_STANDARD)
            + _round_robin([r for r in runs if r["adversarial"]], TILES_ADVERSARIAL))


def _cut(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= TEXT else text[:TEXT].rsplit(" ", 1)[0] + " ..."


def tile(run: dict, language: str) -> dict:
    o = run["outcome"]
    calls = [{"tool": s["name"], "ok": s["error"] is None, "phase": s["meta"].get("phase", "agent")}
             for s in run["steps"] if s["kind"] == "tool"]
    return {
        "id": run["scenario"], "template": run["template"], "adversarial": run["adversarial"], "language": language,
        "success": o["success"], "hazards": o["hazards"], "end": o["end"],
        "turns": [[_cut(t.get("customer")), _cut(t.get("agent"))] for t in run["turns"]],
        "calls": calls,
        # One recorded latency per agent reply, so the demo can replay each call at its real pace.
        "ms": [round(x, 2) for x in o["latency_ms"]],
    }


def attack(scenario, base: dict, cand: dict) -> dict:
    a = scenario.persona.attack or {}
    tools = cand["final_state"].get("tools", {})
    return {
        "id": scenario.id, "kind": a.get("kind", ""), "lines": a.get("lines") or [],
        "planted_calls": [c["tool"] for c in a.get("calls") or []],
        "baseline_hazards": base["outcome"]["hazards"], "candidate_hazards": cand["outcome"]["hazards"],
        "blocked_by_resolver": tools.get("blocked_by_resolver"), "blocked_by_server": tools.get("blocked_by_server"),
        "sent_to_server": tools.get("steered_sent"),
        "turns": [[_cut(t.get("customer")), _cut(t.get("agent"))] for t in cand["turns"]],
    }


def trim_report(rep: dict) -> dict:
    keep = ("baseline", "candidate", "deployment", "evidence_bar", "scenarios", "hypotheses", "gates", "verdict",
            "verdict_line", "calibration")
    out = {k: rep[k] for k in keep}
    for side in ("baseline_summary", "candidate_summary"):
        s = rep[side]
        out[side] = {k: s[k] for k in ("valid", "success_rate", "hazard_runs", "hazards", "abandoned", "mean_turns",
                                       "latency_ms", "tokens")}
        out[side]["cost"] = s["cost"]["total"]
    out["configuration"] = {k: {"version": v["version"], "client_sha": v["client_sha"][:12],
                                "model_ids": v["model_ids"]} for k, v in rep["configuration"].items()}
    return out
