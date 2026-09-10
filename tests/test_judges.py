"""Judges, calibration, cascade and error correlation, plus the model customer, all with a fake model."""

import random

import pytest

from proving import llm
from proving.customer.base import AgentTurn
from proving.customer.llm import LLMCustomer
from proving.report import judging
from proving.scenarios.schema import Fact, Persona
from proving.scoring import judge
from proving.toolsim import proxy as px


def test_platt_scaling_repairs_an_overconfident_judge():
    rng = random.Random(1)
    ys = [rng.random() < 0.5 for _ in range(400)]
    # Says 0.95 or 0.05 every time but is right only 70% of the time.
    ps = [(0.95 if y else 0.05) if rng.random() < 0.7 else (0.05 if y else 0.95) for y in ys]
    raw = judge.reliability(ps, ys)["ece"]
    ab = judge.fit_platt(ps, ys)
    cal = judge.reliability([judge.apply_platt(p, ab) for p in ps], ys)["ece"]
    assert raw > 0.2 and cal < 0.05


def test_effective_judges_from_error_correlation():
    ys = [1, 0] * 50
    same = [0.9 if (i % 7) else 0.1 for i in range(100)]
    out = judge.error_correlation({"a": same, "b": list(same)}, ys)
    assert out["mean_error_correlation"] == pytest.approx(1.0) and out["effective_judges"] == pytest.approx(1.0)
    rng = random.Random(3)
    indep = {n: [y if rng.random() < 0.8 else 1 - y for y in ys] for n in "abcd"}
    out = judge.error_correlation(indep, ys)
    assert abs(out["mean_error_correlation"]) < 0.2 and out["effective_judges"] > 3


def test_cascade_escalates_only_unsure_cases():
    cheap = [0.95, 0.55, 0.1, 0.6]
    strong = [1.0, 0.0, 0.0, 1.0]
    ys = [1, 0, 0, 1]
    rows = {r["threshold"]: r for r in judge.cascade(cheap, strong, ys, thresholds=(0.7,))}
    assert rows[0.7]["escalated"] == 2 and rows[0.7]["accuracy"] == 1.0


def test_heuristic_reads_the_last_agent_line():
    assert judge.heuristic("Customer: hi\nAgent: Your viewing is booked for Monday.")["p"] > 0.5
    assert judge.heuristic("Customer: hi\nAgent: Which day?")["p"] < 0.5


def _run(sid, success):
    return {"scenario": sid, "outcome": {"valid": True, "success": success},
            "turns": [{"customer": "hi", "agent": "Your viewing is booked." if success else "Which day?"}]}


def test_verdicts_need_the_cache_or_a_model():
    items = judging.sample({"v": [_run("a", True), _run("b", False)]}, 2)
    with pytest.raises(llm.ModelUnavailable):
        judging.verdicts(items, {}, use_model=False)


def test_judging_end_to_end_with_a_fake_model(monkeypatch):
    def fake_chat(messages, **kw):
        booked = "booked" in messages[-1]["content"]
        return {"content": f'{{"success": {str(booked).lower()}, "confidence": 0.9, "helpfulness": 4}}',
                "usage": {"total_tokens": 10}}

    monkeypatch.setattr(llm, "chat", fake_chat)
    runs = {"a": [_run(f"s{i}", i % 3 != 0) for i in range(60)], "b": [_run(f"t{i}", i % 2 == 0) for i in range(60)]}
    items = judging.sample(runs, 40)
    cache: dict = {}
    preds = judging.verdicts(items, cache, use_model=True)
    assert len(cache) == 2 * len({judge.transcript_text(r) for _, r in items})
    out = judging.evaluate(items, preds, "fake")
    assert out["calibration"]["status"] == "run"
    assert out["judges"]["per_judge"]["pointwise"]["accuracy_calibrated"] == 1.0
    assert set(out["judges"]["correlation"]["judges"]) == {"heuristic", "pointwise", "sceptical"}
    # A second pass is served entirely from the cache, which is how CI rebuilds these numbers.
    assert judging.verdicts(items, cache, use_model=False)["pointwise"] == preds["pointwise"]


BOOK = {"languages": {"en": {"greet": ["Hi."], "open": ["I want"], "clauses": {"item": ["{item}"]},
                             "answers": {"qty": ["{qty}."]}, "done": ["Bye."], "unknown": ["?"]}}}


def test_model_customer_rewords_through_the_proxy_and_replays(monkeypatch):
    calls = []

    def fake_chat(messages, **kw):
        calls.append(messages)
        return {"content": "Two, please.", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(llm, "chat", fake_chat)
    persona = Persona(language="en", style="plain", patience=3, goal="g",
                      facts=(Fact("item", "tea", "open"), Fact("qty", 2, "asked"), Fact("secret", "x", "never")))
    rec = px.Proxy()
    c = LLMCustomer(persona, BOOK, seed=1, proxy=rec)
    c.opening()
    said = c.respond(AgentTurn("How many?", asks=("qty",)))
    assert said.text == "Two, please."
    assert all("x" not in m[-1]["content"].split("Draft line:")[1] for m in calls)
    rep = px.Proxy(replay=rec.log)
    c2 = LLMCustomer(persona, BOOK, seed=1, proxy=rep)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("model called in replay"))
    c2.opening()
    assert c2.respond(AgentTurn("How many?", asks=("qty",))).text == "Two, please."
