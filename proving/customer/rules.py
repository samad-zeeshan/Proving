"""The offline customer: fixed phrasebook lines, picked by a seeded RNG, so CI needs no model."""

from __future__ import annotations

import random

from ..scenarios.schema import Persona
from . import render
from .base import AgentTurn, GatedCustomer


class RulesCustomer(GatedCustomer):
    kind = "rules"

    def __init__(self, persona: Persona, phrasebook: dict, seed: int = 0) -> None:
        super().__init__(persona, seed, aliases=phrasebook.get("aliases"))
        try:
            self.lang = phrasebook["languages"][persona.language]
        except KeyError as exc:
            raise KeyError(f"phrasebook has no language {persona.language!r}") from exc
        self.rng = random.Random(seed)
        self.values = {f.key: f.value for f in persona.facts}

    def _pick(self, section: str, key: str | None = None) -> str:
        options = self.lang.get(section) or []
        if key is not None:
            options = (options or {}).get(key) or []
        if not options:
            return ""
        values = self.values
        wanted = values.get("choice")
        if key == "choice" and self.options and isinstance(wanted, int) and wanted > self.options:
            # Offered fewer options than the caller had in mind, they take the last one.
            values = {**values, "choice": self.options}
        return render.fill(self.rng.choice(options), values, self.lang)

    def compose(self, plan, agent: AgentTurn | None) -> str:
        opening = [key for kind, key in plan if kind == "open" and key in (self.lang.get("clauses") or {})]
        sentences: list[str] = []
        for kind, key in plan:
            if kind == "greet":
                sentences.append(self._pick("greet"))
                if opening:
                    clauses = " ".join(self._pick("clauses", k) for k in opening)
                    sentences.append(f"{self._pick('open')} {clauses}".strip() + self.lang.get("stop", "."))
            elif kind == "open" and key not in opening:
                sentences.append(self._pick("answers", key))
            elif kind == "reveal":
                sentences.append(self._pick("answers", key) or self._pick("unknown"))
            elif kind in ("deflect", "refuse", "unknown", "hangup", "done", "nudge"):
                sentences.append(self._pick(kind) or self._pick("unknown"))
            elif kind == "attack":
                sentences.append(render.fill(key, self.values, self.lang))
        return " ".join(s for s in sentences if s)
