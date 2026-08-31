"""Which facts a customer may say yet, given how often the agent has asked for each."""

from __future__ import annotations

from ..scenarios.schema import Persona

# Keys the agent is expected to ask about more than once in a normal call, so a second question is
# not the agent forgetting what it was told.
REUSABLE = frozenset({"choice", "confirm", "alternative", "repeat"})


class DisclosureGate:
    def __init__(self, persona: Persona, aliases: dict[str, str] | None = None) -> None:
        self.persona = persona
        # An agent may ask for one thing under another name: "another day?" is a question about the
        # date for a caller who never had a fallback day in mind.
        self.aliases = aliases or {}
        self.asked: dict[str, int] = {}
        self.said: set[str] = {f.key for f in persona.facts if f.gate == "open"}

    def resolve(self, key: str) -> str:
        if self.persona.fact(key) is None and self.persona.fact(self.aliases.get(key, "")) is not None:
            return self.aliases[key]
        return key

    def unlocked(self) -> set[str]:
        return set(self.said)

    def observe(self, asks) -> dict[str, str]:
        """Record one agent turn's questions and say what the customer does about each."""
        out: dict[str, str] = {}
        for key in (self.resolve(k) for k in asks):
            self.asked[key] = self.asked.get(key, 0) + 1
            fact = self.persona.fact(key)
            if fact is None:
                out[key] = "unknown"
            elif fact.gate == "never":
                out[key] = "refuse"
            elif fact.gate == "asked_twice" and self.asked[key] < 2 and key not in self.said:
                out[key] = "deflect"
            else:
                out[key] = "reveal"
                self.said.add(key)
        return out

    def already_said(self, key: str) -> bool:
        return key in self.said and key not in REUSABLE
