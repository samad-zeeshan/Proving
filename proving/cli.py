"""Command line: generate scenarios, simulate, compare versions, replay, report.

This file is where adapters are loaded by name. Nothing else in the core imports one.
"""

from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path

from .scenarios import generator, schema

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "scenarios"


def _adapter(name: str):
    from . import adapters

    return adapters.load(name)


@functools.lru_cache(maxsize=None)
def _load_all(client: str) -> tuple[schema.Scenario, ...]:
    return tuple(schema.load_dir(SCENARIOS / client / "generated"))


def scenario_set(client: str, which: str = "all") -> list[schema.Scenario]:
    loaded = list(_load_all(client))
    if which == "all":
        return loaded
    if which == "smoke":
        return generator.smoke_set(loaded, 20)
    if which == "adversarial":
        return [s for s in loaded if s.adversarial]
    if which == "standard":
        return [s for s in loaded if not s.adversarial]
    return [s for s in loaded if s.hypothesis == which or s.template == which or s.id == which]


def cmd_generate(args) -> int:
    adapter = _adapter(args.client)
    scenarios = generator.generate(SCENARIOS / args.client / "templates.yaml", builders=adapter.builders())
    paths = generator.write_all(scenarios, SCENARIOS / args.client / "generated")
    adversarial = sum(s.adversarial for s in scenarios)
    print(f"{args.client}: {len(paths)} scenarios ({adversarial} adversarial) from "
          f"{len({s.template for s in scenarios})} templates")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="proving", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="expand a client's templates into scenario files")
    g.add_argument("client")
    g.set_defaults(fn=cmd_generate)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
