"""The scenario file: persona, starting tool state, success criteria, hazards and a hypothesis tag.

Loading validates everything, so a bad template fails at generation time, not halfway through a run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Ordered from most to least forthcoming, after the disclosure ladder in arXiv 2609.00982.
# "asked_twice" is the reluctant customer: the first question gets a deflection.
GATES = ("open", "asked", "asked_twice", "never")
STYLES = ("plain", "terse", "chatty", "impatient", "hostile")
LANGUAGES = ("en", "ar-gulf", "ar-msa", "mixed")


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    gate: str = "open"


@dataclass(frozen=True)
class Persona:
    language: str
    style: str
    patience: int
    goal: str
    facts: tuple[Fact, ...] = ()
    attack: dict | None = None

    def fact(self, key: str) -> Fact | None:
        return next((f for f in self.facts if f.key == key), None)


@dataclass(frozen=True)
class Hazard:
    id: str
    when: dict


@dataclass(frozen=True)
class Scenario:
    id: str
    client: str
    template: str
    seed: int
    hypothesis: str
    persona: Persona
    tool_state: dict = field(default_factory=dict)
    success: tuple[dict, ...] = ()
    hazards: tuple[Hazard, ...] = ()
    adversarial: bool = False


def _require(raw: dict, key: str, where: str) -> Any:
    if key not in raw:
        raise SchemaError(f"{where}: missing {key!r}")
    return raw[key]


def _fact(raw: dict, where: str) -> Fact:
    key = raw.get("key")
    if not isinstance(key, str) or not key:
        raise SchemaError(f"{where}: fact key must be a non-empty string")
    gate = raw.get("gate", "open")
    if gate not in GATES:
        raise SchemaError(f"{where}: fact {key!r} has gate {gate!r}, expected one of {GATES}")
    return Fact(key=key, value=raw.get("value"), gate=gate)


def _persona(raw: dict, where: str) -> Persona:
    language = _require(raw, "language", where)
    style = raw.get("style", "plain")
    if language not in LANGUAGES:
        raise SchemaError(f"{where}: language {language!r} not in {LANGUAGES}")
    if style not in STYLES:
        raise SchemaError(f"{where}: style {style!r} not in {STYLES}")
    patience = _require(raw, "patience", where)
    if not isinstance(patience, int) or patience < 1:
        raise SchemaError(f"{where}: patience must be a positive integer")
    facts = tuple(_fact(f, where) for f in raw.get("facts") or ())
    keys = [f.key for f in facts]
    if len(keys) != len(set(keys)):
        raise SchemaError(f"{where}: duplicate fact keys")
    return Persona(language=language, style=style, patience=patience,
                   goal=str(_require(raw, "goal", where)), facts=facts, attack=raw.get("attack"))


def from_dict(raw: dict) -> Scenario:
    from .predicates import check

    where = str(raw.get("id", "<scenario>"))
    success = tuple(raw.get("success") or ())
    for pred in success:
        check(pred)
    hazards = []
    for h in raw.get("hazards") or ():
        check(_require(h, "when", where))
        hazards.append(Hazard(id=str(_require(h, "id", where)), when=h["when"]))
    return Scenario(
        id=str(_require(raw, "id", where)),
        client=str(_require(raw, "client", where)),
        template=str(_require(raw, "template", where)),
        seed=int(_require(raw, "seed", where)),
        hypothesis=str(_require(raw, "hypothesis", where)),
        persona=_persona(_require(raw, "persona", where), where),
        tool_state=dict(raw.get("tool_state") or {}),
        success=success,
        hazards=tuple(hazards),
        adversarial=bool(raw.get("adversarial", False)),
    )


def to_dict(s: Scenario) -> dict:
    persona = asdict(s.persona)
    persona["facts"] = [asdict(f) for f in s.persona.facts]
    if persona["attack"] is None:
        del persona["attack"]
    return _plain({
        "id": s.id, "client": s.client, "template": s.template, "seed": s.seed,
        "hypothesis": s.hypothesis, "adversarial": s.adversarial, "persona": persona,
        "tool_state": s.tool_state, "success": list(s.success),
        "hazards": [{"id": h.id, "when": h.when} for h in s.hazards],
    })


def _plain(obj: Any) -> Any:
    # yaml.safe_dump refuses tuples, and the frozen dataclasses hold them.
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


def dump(s: Scenario) -> str:
    # Flow style for leaf lists and maps keeps an inventory of slots readable and a tenth of the size.
    return yaml.safe_dump(to_dict(s), sort_keys=False, allow_unicode=True, width=110, default_flow_style=None)


# The C loader reads the two thousand scenario files about ten times faster when libyaml is present.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load(path: Path) -> Scenario:
    return from_dict(yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_LOADER))


def load_dir(directory: Path) -> list[Scenario]:
    return [load(p) for p in sorted(Path(directory).glob("*.yaml"))]
