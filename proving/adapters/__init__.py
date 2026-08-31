"""Client adapters, loaded by name so the core never imports one."""

from __future__ import annotations

import importlib

REGISTRY = {
    "warden": "proving.adapters.warden:WardenAdapter",
    "parley": "proving.adapters.parley:ParleyAdapter",
}


def load(name: str):
    target = REGISTRY.get(name, name)
    module, _, cls = target.partition(":")
    return getattr(importlib.import_module(module), cls)()
