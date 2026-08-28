"""The customer interface and the turn loop both customer types share.

Gating and patience live here, so the model-driven customer cannot say a fact the rules would hold
back. It only chooses the words.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..scenarios.schema import Persona
from .gate import DisclosureGate


@dataclass
class AgentTurn:
    text: str
    asks: tuple[str, ...] = ()
    action: str = ""
    done: bool = False
    friction: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class CustomerTurn:
    text: str
    disclosed: tuple[str, ...] = ()
    hang_up: bool = False
    reason: str = ""
    plan: list = field(default_factory=list)


class GatedCustomer:
    """Decides what to say each turn. Subclasses decide how to say it."""

    kind = "base"

    def __init__(self, persona: Persona, seed: int = 0) -> None:
        self.persona = persona
        self.seed = seed
        self.gate = DisclosureGate(persona)
        self.patience = persona.patience
        self.turn = 0
        self.last_text = ""
        attack = persona.attack or {}
        self._attack_lines = list(attack.get("lines") or [])
        self._attack_when = attack.get("when", "open")

    def _attack(self, trigger: str) -> list[tuple[str, str]]:
        if self._attack_lines and self._attack_when in (trigger, "every"):
            return [("attack", self._attack_lines.pop(0))]
        return []

    def opening(self) -> CustomerTurn:
        plan = [("greet", "")] + [("open", f.key) for f in self.persona.facts if f.gate == "open"]
        plan += self._attack("open")
        return self._finish(plan, tuple(f.key for f in self.persona.facts if f.gate == "open"), None)

    def respond(self, agent: AgentTurn) -> CustomerTurn:
        self.turn += 1
        if agent.done:
            return self._finish([("done", "")], (), agent, hang_up=True, reason="done")
        if "repeat" in agent.asks:
            return CustomerTurn(text=self.last_text, plan=[("repeat", "")])
        cost = 1 if agent.friction else 0
        if not agent.asks and not agent.friction:
            cost = 1  # the agent stalled without asking anything
        cost += sum(1 for k in agent.asks if self.gate.already_said(k))
        # Impatient customers pay double for the same friction, the style PersonaForge calls low tolerance.
        if self.persona.style == "impatient":
            cost *= 2
        self.patience -= cost
        if self.patience <= 0:
            return self._finish([("hangup", "")], (), agent, hang_up=True, reason="patience")
        decisions = self.gate.observe(agent.asks)
        plan = [(d, k) for k, d in decisions.items()]
        for k in agent.asks:
            plan += self._attack(k)
        if not plan:
            plan = [("nudge", "")]
        disclosed = tuple(k for k, d in decisions.items() if d == "reveal")
        return self._finish(plan, disclosed, agent)

    def _finish(self, plan, disclosed, agent, hang_up=False, reason="") -> CustomerTurn:
        text = self.compose(plan, agent)
        self.last_text = text
        return CustomerTurn(text=text, disclosed=disclosed, hang_up=hang_up, reason=reason, plan=plan)

    def compose(self, plan: list[tuple[str, str]], agent: AgentTurn | None) -> str:
        raise NotImplementedError
