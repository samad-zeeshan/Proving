"""The core never imports an adapter. Only the command line loads one, by name."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "proving"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            names += [f"{base}:{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names += [a.name for a in node.names]
    return names


def test_core_does_not_import_adapters():
    offenders = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG)
        if rel.parts[0] == "adapters" or rel.name == "cli.py":
            continue
        for name in _imports(path):
            if "adapters" in name.replace(":", ".").split("."):
                offenders.append(f"{rel}: {name}")
    assert offenders == []


def test_cli_loads_adapters_through_the_registry_only():
    assert [n for n in _imports(PKG / "cli.py") if "adapters" in n] == [".:adapters"]
