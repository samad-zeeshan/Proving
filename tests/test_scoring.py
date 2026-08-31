"""Deterministic scoring and Total-Cost-of-Agency attribution."""

import pytest

from proving.scenarios.schema import Hazard, Persona, Scenario
from proving.scoring import cost, deterministic


def scenario(**kw):
    base = dict(
        id="s1", client="toy", template="t", seed=1, hypothesis="h",
        persona=Persona(language="en", style="plain", patience=2, goal="g"),
        success=({"path": "tools.orders", "op": "eq", "value": 1},),
        hazards=(Hazard("double", {"path": "tools.orders", "op": "gt", "value": 1}),
                 Hazard("wrong_phone", {"path": "tools.phone", "op": "ne", "value": "050"})),
    )
    base.update(kw)
    return Scenario(**base)


def run(tools, end="done", turns=None, steps=None):
    turns = turns if turns is not None else [
        {"i": 0, "customer": "hi", "agent": "hello", "latency_ms": 10.0, "nodes": {}},
        {"i": 1, "customer": "order", "agent": "done", "latency_ms": 30.0, "nodes": {}},
        {"i": 2, "customer": "bye", "agent": None, "hang_up": "done"},
    ]
    return {"final_state": {"tools": tools, "agent": {}}, "end": end, "turns": turns, "steps": steps or [],
            "divergence": None}


def test_success_and_hazards():
    out = deterministic.score_run(scenario(), run({"orders": 1, "phone": "050"}))
    assert out["success"] is True and out["hazards"] == []
    out = deterministic.score_run(scenario(), run({"orders": 2, "phone": "051"}))
    assert out["success"] is False and out["hazards"] == ["double", "wrong_phone"]


def test_turns_latency_and_end():
    out = deterministic.score_run(scenario(), run({"orders": 1, "phone": "050"}))
    assert out["agent_turns"] == 2
    assert out["latency_ms"] == [10.0, 30.0]
    assert out["abandoned"] is False
    assert deterministic.score_run(scenario(), run({}, end="patience"))["abandoned"] is True


def test_diverged_run_is_not_scored_as_a_success():
    r = run({"orders": 1, "phone": "050"}, end="diverged")
    r["divergence"] = {"step": 3}
    out = deterministic.score_run(scenario(), r)
    assert out["success"] is None and out["valid"] is False


def test_tool_counts_from_steps():
    steps = [
        {"kind": "tool", "name": "a", "error": None, "meta": {}, "ms": 1.0},
        {"kind": "tool", "name": "b", "error": {"type": "x", "message": "m"}, "meta": {}, "ms": 2.0},
        {"kind": "model", "name": "nlu", "error": None, "meta": {}, "ms": 5.0},
    ]
    out = deterministic.score_run(scenario(), run({"orders": 1, "phone": "050"}, steps=steps))
    assert out["tool_calls"] == 2 and out["tool_errors"] == 1 and out["model_calls"] == 1


def _model(node, prompt, stripped, completion, missed=False, history=0):
    return {"kind": "model", "name": "nlu", "error": None, "ms": 1.0,
            "meta": {"node": node, "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
                     "stripped_prompt_tokens": stripped, "missed": missed, "history_tokens": history}}


def test_total_cost_of_agency_partitions_tokens():
    steps = [_model("nlu", 300, 250, 40), _model("nlu", 320, 250, 35, missed=True),
             _model("phrasing", 500, 380, 60, history=100)]
    tca = cost.attribute(steps)
    nlu, phr = tca["by_node"]["nlu"], tca["by_node"]["phrasing"]
    assert nlu == {"base_prompt": 250, "inference": 40, "injected_context": 50, "miss_penalty": 355,
                   "accumulation": 0, "total": 695, "calls": 2}
    assert phr["accumulation"] == 100 and phr["base_prompt"] == 280 and phr["injected_context"] == 120
    total = tca["total"]
    assert total["total"] == 695 + 560
    assert sum(total[k] for k in cost.COMPONENTS) == total["total"]


def test_cost_of_a_run_without_models_is_zero():
    tca = cost.attribute([{"kind": "tool", "name": "a", "meta": {}, "error": None}])
    assert tca["total"]["total"] == 0 and tca["by_node"] == {}


def test_counter_mismatch_is_reported():
    step = _model("nlu", 300, 320, 10)  # stripped larger than full: a counting bug, not negative cost
    with pytest.raises(ValueError, match="stripped"):
        cost.attribute([step])
