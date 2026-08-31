"""The Parley adapter: generated set, smoke run, synth against the real service, replay and noise."""

import re

import pytest

from proving import cli, llm
from proving.runner import run_scenario
from proving.scoring.deterministic import score_run, stable

pytestmark = pytest.mark.clients


@pytest.fixture(scope="module")
def scenarios(parley):
    return {s.id: s for s in cli.scenario_set("parley")}


def test_generated_set_meets_the_spec(scenarios):
    standard = [s for s in scenarios.values() if not s.adversarial]
    adversarial = [s for s in scenarios.values() if s.adversarial]
    assert len(standard) >= 200 and len(adversarial) >= 30
    assert len({s.template for s in scenarios.values()}) <= 20


def test_smoke_set_runs_offline_on_the_synthesizer(parley):
    for s in cli.scenario_set("parley", "smoke"):
        run = run_scenario(parley, s, "rules")
        assert run["mode"] == "synthesize"
        assert score_run(s, run)["valid"], s.id
        assert {st["source"] for st in run["steps"] if st["kind"] == "tool"} <= {"synth"}


def _shape(run, outcome):
    # Booking ids differ between the two backends. Everything a scorer reads must not.
    return {"success": outcome["success"], "hazards": outcome["hazards"], "turns": outcome["agent_turns"],
            "actions": [t.get("action") for t in run["turns"]],
            "calls": [(st["name"], st["error"]["type"] if st["error"] else None) for st in run["steps"]]}


def test_synthesizer_agrees_with_the_real_booking_service(parley):
    for s in cli.scenario_set("parley", "smoke"):
        synth = run_scenario(parley, s, "rules", backend="synth")
        real = run_scenario(parley, s, "rules", backend="live")
        assert _shape(synth, score_run(s, synth)) == _shape(real, score_run(s, real)), s.id


def test_synthesized_ids_match_parley_schemas(parley, scenarios):
    run = run_scenario(parley, scenarios["pl-en-direct-000"], "rules")
    holds = [st["out"]["hold_id"] for st in run["steps"] if st["name"] == "hold_slot" and st["out"]]
    books = [st["out"]["booking_id"] for st in run["steps"] if st["name"] == "confirm_booking" and st["out"]]
    assert holds and all(re.fullmatch(r"h-[0-9a-f]{12}", h) for h in holds)
    assert books and all(re.fullmatch(r"b-[0-9a-f]{12}", b) for b in books)


def _second_choice(scenarios):
    return next(s for s in scenarios.values()
                if s.template == "en-direct" and s.persona.fact("choice").value >= 2)


def test_full_replay_is_identical(parley, scenarios):
    s = _second_choice(scenarios)
    recorded = run_scenario(parley, s, "rules")
    again = run_scenario(parley, s, "rules", replay_run=recorded)
    assert again["divergence"] is None
    assert stable(score_run(s, again)) == stable(score_run(s, recorded))


def test_regression_replay_catches_a_deliberate_regression(parley, scenarios):
    s = _second_choice(scenarios)
    recorded = run_scenario(parley, s, "rules")
    assert score_run(s, recorded)["success"] is True
    # Full replay: the broken build asks to hold a different slot than the record, and stops there.
    full = run_scenario(parley, s, "rules-regressed", replay_run=recorded)
    assert full["end"] == "diverged"
    assert full["divergence"]["expected"]["name"] == "hold_slot"
    # Cut-point replay: serve the record up to the hold, run the broken build live from there on.
    hold_step = next(st["step"] for st in recorded["steps"] if st["name"] == "hold_slot")
    cut = run_scenario(parley, s, "rules-regressed", replay_run=recorded, cut=hold_step)
    out = score_run(s, cut)
    assert cut["divergence"] is None and out["success"] is False
    assert "wrong_booking" in out["hazards"]


def test_model_version_refuses_to_run_without_a_model(parley, scenarios, monkeypatch):
    monkeypatch.delenv("PROVING_LLM", raising=False)
    with pytest.raises(llm.ModelUnavailable):
        run_scenario(parley, scenarios["pl-en-direct-000"], "llm")


def test_noise_channel_produces_about_the_asked_word_error_rate(parley):
    errors = words = 0
    for s in cli.scenario_set("parley", "standard")[:60]:
        ch = run_scenario(parley, s, "rules|noise@0.2")["final_state"]["channel"]
        errors, words = errors + ch["word_errors"], words + ch["words"]
    assert 0.12 < errors / words < 0.28


def test_split_channel_sends_two_messages(parley, scenarios):
    run = run_scenario(parley, scenarios["pl-en-direct-000"], "rules|split")
    assert " / " in run["turns"][0]["agent"]
