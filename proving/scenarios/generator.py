"""Expand a client's templates into scenario files from one seed.

Each template draws its variables, asks an optional builder for the starting tool state, then fills
the persona, success criteria and hazards. Same seed, same files, byte for byte.
"""

from __future__ import annotations

import hashlib
import random
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from . import schema

MAX_TEMPLATES = 20
Builder = Callable[[dict, random.Random], tuple[dict, dict]]

_WHOLE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")
_INLINE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def scenario_seed(base: int, template: str, k: int) -> int:
    # Hashing the template id, not its position, keeps every other template's scenarios unchanged
    # when one template is added or reordered.
    digest = hashlib.sha256(f"{base}:{template}:{k}".encode()).hexdigest()
    return int(digest[:8], 16)


def _draw(spec: dict, rng: random.Random) -> Any:
    if "choice" in spec:
        return rng.choice(spec["choice"])
    if "int" in spec:
        lo, hi = spec["int"]
        return rng.randint(lo, hi)
    if "phone" in spec:
        # UAE mobile numbers as Parley's schema accepts them. The fixed 050000 prefix is left out
        # because the seeded agency staff use it.
        return "05" + str(rng.choice([0, 2, 4, 5, 6, 8])) + "".join(str(rng.randint(0, 9)) for _ in range(7))
    raise schema.SchemaError(f"unknown variable spec {spec!r}")


def substitute(obj: Any, env: dict) -> Any:
    if isinstance(obj, dict):
        return {k: substitute(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, env) for v in obj]
    if isinstance(obj, str):
        whole = _WHOLE.match(obj)
        if whole:
            name = whole.group(1)
            if name not in env:
                raise schema.SchemaError(f"unknown variable ${name}")
            return env[name]

        def inline(m: re.Match) -> str:
            if m.group(1) not in env:
                raise schema.SchemaError(f"unknown variable ${{{m.group(1)}}}")
            return str(env[m.group(1)])

        return _INLINE.sub(inline, obj)
    return obj


def load_templates(path: Path) -> dict:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    templates = doc.get("templates") or []
    if len(templates) > MAX_TEMPLATES:
        raise schema.SchemaError(f"{path}: {len(templates)} templates, at most {MAX_TEMPLATES} templates allowed")
    ids = [t["id"] for t in templates]
    if len(ids) != len(set(ids)):
        raise schema.SchemaError(f"{path}: duplicate template ids")
    return doc


def generate(path: Path, builders: dict[str, Builder] | None = None) -> list[schema.Scenario]:
    doc = load_templates(path)
    builders = builders or {}
    base = int(doc.get("seed", 0))
    prefix = doc.get("prefix", doc["client"])
    out: list[schema.Scenario] = []
    for tpl in doc["templates"]:
        for k in range(int(tpl.get("count", 1))):
            seed = scenario_seed(base, tpl["id"], k)
            rng = random.Random(seed)
            env = {name: _draw(spec, rng) for name, spec in (tpl.get("vars") or {}).items()}
            tool_state = tpl.get("tool_state") or {}
            if "builder" in tool_state:
                name = tool_state["builder"]
                if name not in builders:
                    raise schema.SchemaError(f"template {tpl['id']}: no builder {name!r}")
                tool_state, derived = builders[name](substitute(tool_state.get("params", {}), env), rng)
                env.update(derived)
            raw = {
                "id": f"{prefix}-{tpl['id']}-{k:03d}",
                "client": doc["client"],
                "template": tpl["id"],
                "seed": seed,
                "hypothesis": tpl["hypothesis"],
                "adversarial": bool(tpl.get("adversarial", False)),
                "persona": substitute(tpl["persona"], env),
                "tool_state": substitute(tool_state, env),
                "success": substitute(tpl.get("success") or [], env),
                "hazards": substitute(tpl.get("hazards") or [], env),
            }
            out.append(schema.from_dict(raw))
    return out


def write_all(scenarios: list[schema.Scenario], directory: Path) -> list[Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    keep = set()
    for s in scenarios:
        path = directory / f"{s.id}.yaml"
        text = schema.dump(s)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8", newline="\n")
        keep.add(path.name)
    # A template whose count went down would otherwise leave old files that still get run.
    for stale in directory.glob("*.yaml"):
        if stale.name not in keep:
            stale.unlink()
    return sorted(directory / name for name in keep)


def smoke_set(scenarios: list[schema.Scenario], n: int) -> list[schema.Scenario]:
    by_template: dict[str, list[schema.Scenario]] = {}
    for s in scenarios:
        by_template.setdefault(s.template, []).append(s)
    picked: list[schema.Scenario] = []
    rank = 0
    while len(picked) < n and any(rank < len(v) for v in by_template.values()):
        for group in by_template.values():
            if rank < len(group) and len(picked) < n:
                picked.append(group[rank])
        rank += 1
    return picked
