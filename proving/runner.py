"""Run one scenario: a customer and an agent take turns until one of them ends the call.

Every tool, model and customer boundary goes through one proxy, so the run can be saved and replayed.
"""

from __future__ import annotations

import time

from .customer.rules import RulesCustomer
from .interface import Adapter
from .scenarios.schema import Scenario
from .toolsim.proxy import Envelope, Proxy, ReplayDivergence

MAX_TURNS = 16


class TranscriptDivergence(ReplayDivergence):
    pass


def make_customer(kind: str, scenario: Scenario, phrasebook: dict, proxy: Proxy):
    if kind == "rules":
        return RulesCustomer(scenario.persona, phrasebook, seed=scenario.seed)
    if kind == "llm":
        from .customer.llm import LLMCustomer

        return LLMCustomer(scenario.persona, phrasebook, seed=scenario.seed, proxy=proxy)
    raise ValueError(f"unknown customer {kind!r}")


def run_scenario(adapter: Adapter, scenario: Scenario, version: str, *, customer: str = "rules",
                 backend: str | None = None, replay_run: dict | None = None, cut: int | None = None,
                 max_turns: int = MAX_TURNS) -> dict:
    backend = backend or adapter.default_backend
    steps = [Envelope.from_dict(d) for d in replay_run["steps"]] if replay_run else None
    proxy = Proxy(backend=backend, replay=steps, cut=cut, errors=adapter.errors())
    cust = make_customer(customer, scenario, adapter.phrasebook(), proxy)
    session = adapter.session(scenario, version, proxy)
    full_replay = replay_run is not None and cut is None
    turns: list[dict] = []
    end, divergence = "max_turns", None
    try:
        said = cust.opening()
        for i in range(max_turns):
            t0 = time.perf_counter()
            agent = session.send(said.text)
            ms = round((time.perf_counter() - t0) * 1000, 3)
            if proxy.diverged:
                raise proxy.diverged
            turns.append({
                "i": i, "customer": said.text, "disclosed": list(said.disclosed), "agent": agent.text,
                "action": agent.action, "asks": list(agent.asks), "done": agent.done,
                "friction": agent.friction, "latency_ms": ms, "nodes": agent.meta.get("nodes", {}),
            })
            if full_replay:
                _check_transcript(replay_run, i, said.text, agent.text)
            said = cust.respond(agent)
            if said.hang_up:
                turns.append({"i": i + 1, "customer": said.text, "disclosed": [], "agent": None,
                              "hang_up": said.reason})
                end = said.reason
                break
        proxy.finish()
    except ReplayDivergence as exc:
        end = "diverged"
        divergence = {"step": exc.step, "expected": exc.expected, "got": exc.got, "message": str(exc)}
    # A full replay never touches the backend, so its state is the recorded one. That holds only
    # because every step matched: a divergence stops the run before this line matters.
    if full_replay and divergence is None:
        final = replay_run["final_state"]
    else:
        final = session.final_state()
    return {
        "scenario": scenario.id, "client": scenario.client, "template": scenario.template,
        "hypothesis": scenario.hypothesis, "adversarial": scenario.adversarial, "version": version,
        "customer": customer, "backend": backend, "mode": proxy.mode, "cut": cut,
        "steps": [e.to_dict() for e in proxy.log], "turns": turns, "end": end,
        "divergence": divergence, "sync_mismatches": proxy.sync_mismatches, "final_state": final,
    }


def _check_transcript(replay_run: dict, i: int, customer_text: str, agent_text: str) -> None:
    recorded = replay_run["turns"]
    if i >= len(recorded) or recorded[i].get("agent") is None:
        raise TranscriptDivergence(i, None, {"agent": agent_text}, "a turn beyond the recorded call")
    want = recorded[i]
    if want["customer"] != customer_text or want["agent"] != agent_text:
        raise TranscriptDivergence(i, {"customer": want["customer"], "agent": want["agent"]},
                                   {"customer": customer_text, "agent": agent_text},
                                   f"turn {i} reads differently")
