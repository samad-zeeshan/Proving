"""Score one run from its final tool state and transcript: success, hazards, turns, latency, calls, cost."""

from __future__ import annotations

from ..scenarios.predicates import evaluate
from ..scenarios.schema import Scenario
from . import cost

# Wall-clock numbers change on every run. Replays and CI compare everything else.
VOLATILE = ("latency_ms",)


def score_run(scenario: Scenario, run: dict) -> dict:
    final = run.get("final_state") or {}
    agent_turns = [t for t in run["turns"] if t.get("agent") is not None]
    state = {**final, "run": {"end": run["end"], "agent_turns": len(agent_turns)}}
    valid = run.get("divergence") is None and run["end"] != "diverged"
    steps = run.get("steps") or []
    tools = [s for s in steps if s["kind"] == "tool"]
    return {
        "scenario": scenario.id,
        "valid": valid,
        # A diverged replay says nothing about the agent, so it is neither a success nor a failure.
        "success": all(evaluate(p, state) for p in scenario.success) if valid else None,
        "hazards": [h.id for h in scenario.hazards if evaluate(h.when, state)] if valid else [],
        "agent_turns": len(agent_turns),
        "end": run["end"],
        "abandoned": run["end"] == "patience",
        "latency_ms": [t["latency_ms"] for t in agent_turns if "latency_ms" in t],
        "tool_calls": len(tools),
        "tool_errors": sum(1 for s in tools if s.get("error")),
        "model_calls": sum(1 for s in steps if s["kind"] == "model"),
        "cost": cost.attribute(steps),
    }


def stable(outcome: dict) -> dict:
    return {k: v for k, v in outcome.items() if k not in VOLATILE}
