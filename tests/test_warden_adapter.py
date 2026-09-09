"""The Warden adapter end to end: smoke set, resolver effect, replay and divergence."""

import pytest

from proving import cli
from proving.runner import run_scenario
from proving.scoring.deterministic import score_run, stable

pytestmark = pytest.mark.clients


@pytest.fixture(scope="module")
def scenarios(warden):
    return {s.id: s for s in cli.scenario_set("warden")}


def test_generated_set_meets_the_spec(scenarios):
    standard = [s for s in scenarios.values() if not s.adversarial]
    adversarial = [s for s in scenarios.values() if s.adversarial]
    assert len(standard) >= 200 and len(adversarial) >= 30
    assert len({s.template for s in scenarios.values()}) <= 20


def test_smoke_set_runs_offline(warden):
    for s in cli.scenario_set("warden", "smoke"):
        run = run_scenario(warden, s, "v2")
        out = score_run(s, run)
        assert out["valid"], s.id
        assert out["hazards"] == [], (s.id, out["hazards"])
        assert run["mode"] == "record" and run["turns"][0]["agent"].startswith("Decision")


def test_resolver_keeps_malformed_calls_off_the_server(warden, scenarios):
    s = next(x for x in scenarios.values() if x.template == "attack-invented-tools")
    on = run_scenario(warden, s, "v2")["final_state"]["tools"]
    off = run_scenario(warden, s, "resolver-off")["final_state"]["tools"]
    assert on["steered_calls"] == off["steered_calls"] > 0
    assert on["steered_sent"] == 0 and on["blocked_by_resolver"] == on["steered_calls"]
    assert off["steered_sent"] == off["steered_calls"] and off["blocked_by_server"] == off["steered_calls"]
    assert on["steered_writes_succeeded"] == off["steered_writes_succeeded"] == 0


def test_full_replay_matches_without_touching_the_backend(warden, scenarios):
    s = scenarios["wd-attack-other-tenant-000"]
    recorded = run_scenario(warden, s, "v2")
    again = run_scenario(warden, s, "v2", replay_run=recorded)
    assert again["mode"] == "replay" and again["divergence"] is None
    assert {st["source"] for st in again["steps"]} == {"served"}
    assert stable(score_run(s, again)) == stable(score_run(s, recorded))


def test_replay_against_another_version_diverges(warden, scenarios):
    s = next(x for x in scenarios.values() if x.template == "attack-forged-arguments")
    recorded = run_scenario(warden, s, "resolver-off")
    again = run_scenario(warden, s, "v2", replay_run=recorded)
    assert again["end"] == "diverged"
    assert again["divergence"]["expected"]["kind"] == "tool"


def test_cli_simulate_then_replay(warden, tmp_path):
    out = tmp_path / "v2.smoke.jsonl.gz"
    assert cli.main(["simulate", "warden", "--version", "v2", "--set", "smoke", "--out", str(out)]) == 0
    assert cli.main(["replay", "warden", "--runs", str(out)]) == 0
    # The same record replayed against the resolver-off build is flagged.
    assert cli.main(["replay", "warden", "--runs", str(out), "--version", "resolver-off"]) == 1
