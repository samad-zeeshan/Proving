"""Version comparison and the ship, hold or more-evidence gate, on synthetic runs."""

from proving.report import compare, enterprise


def _run(sid, success, hazards=(), metric=0, adversarial=False, tokens=0):
    return {
        "scenario": sid, "adversarial": adversarial, "hypothesis": "h", "template": "t",
        "final_state": {"tools": {"sent": metric}},
        "turns": [{"agent": "x", "latency_ms": 5.0}],
        "outcome": {"valid": True, "success": success, "hazards": list(hazards), "agent_turns": 1,
                    "abandoned": False, "latency_ms": [5.0], "tool_calls": 2, "tool_errors": 0, "model_calls": 0,
                    "end": "done",
                    "cost": {"by_node": {}, "total": {"base_prompt": tokens, "inference": 0, "injected_context": 0,
                                                      "miss_penalty": 0, "accumulation": 0, "total": tokens,
                                                      "calls": 0}}},
    }


HYP = {"id": "h1", "claim": "B sends fewer", "metric": "tools.sent", "direction": "decrease",
       "min_effect": 0.5, "set": "adversarial"}


def _pair(n=400, sent_a=2, sent_b=0, hazard_every=0):
    a, b = [], []
    for i in range(n):
        adv = i % 4 == 0
        hz = ("x",) if hazard_every and i % hazard_every == 0 else ()
        a.append(_run(f"s{i}", True, metric=sent_a if adv else 0, adversarial=adv))
        b.append(_run(f"s{i}", True, hazards=hz, metric=sent_b if adv else 0, adversarial=adv))
    return a, b


def test_hypothesis_uses_only_its_scenario_set_and_pairs_by_id():
    a, b = _pair()
    h = compare.hypothesis(HYP, a, list(reversed(b)), level=0.95)
    assert h["n"] == 100
    assert h["baseline_mean"] == 2 and h["candidate_mean"] == 0
    assert h["verdict"] == "confirmed" and h["ci"][0] > 0


def test_success_metric_and_invalid_runs():
    a = [_run("s1", True), _run("s2", False)]
    b = [_run("s1", True), _run("s2", True)]
    b[1]["outcome"]["valid"] = False
    h = compare.hypothesis({**HYP, "metric": "success", "direction": "increase", "set": "all"}, a, b, level=0.95)
    assert h["n"] == 1 and h["excluded"] == 1


def test_gate_ships_a_safe_confirmed_change():
    # Zero hazards in 800 runs keeps the 99% upper bound under the strict bar of 1%. 400 would not.
    a, b = _pair(n=800)
    bar = enterprise.evidence_bar("A3", "high")
    report = enterprise.gate(bar, compare.summarise(a), compare.summarise(b), compare.deltas(a, b, bar["confidence"]),
                             [compare.hypothesis(HYP, a, b, bar["confidence"])])
    assert report["verdict"] == "ship", report["gates"]


def test_gate_holds_when_hazards_exceed_the_bar():
    a, b = _pair(hazard_every=10)
    bar = enterprise.evidence_bar("A3", "high")
    report = enterprise.gate(bar, compare.summarise(a), compare.summarise(b), compare.deltas(a, b, bar["confidence"]),
                             [compare.hypothesis(HYP, a, b, bar["confidence"])])
    assert report["verdict"] == "hold"
    assert any(g["gate"] == "hazard rate" and not g["passed"] for g in report["gates"])


def test_gate_asks_for_more_evidence_on_a_small_sample():
    a, b = _pair(n=40)
    bar = enterprise.evidence_bar("A3", "high")
    report = enterprise.gate(bar, compare.summarise(a), compare.summarise(b), compare.deltas(a, b, bar["confidence"]),
                             [compare.hypothesis(HYP, a, b, bar["confidence"])])
    assert report["verdict"] == "needs more evidence"


def test_gate_holds_a_refuted_change():
    a, b = _pair(sent_a=0, sent_b=0)
    bar = enterprise.evidence_bar("A3", "low")
    report = enterprise.gate(bar, compare.summarise(a), compare.summarise(b), compare.deltas(a, b, bar["confidence"]),
                             [compare.hypothesis(HYP, a, b, bar["confidence"])])
    assert report["verdict"] == "hold"


def test_summary_counts():
    a, _ = _pair(n=8)
    s = compare.summarise(a)
    assert s["runs"] == 8 and s["success_rate"] == 1.0 and s["hazard_runs"] == 0
    assert s["latency_ms"]["p50"] == 5.0
