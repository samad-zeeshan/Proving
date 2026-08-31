"""Tokens per node, split the Total Cost of Agency way (arXiv 2609.23790).

Each model call is counted twice without billing: once as sent, once with the injected context taken
out. The difference is the injected context, measured rather than estimated from word counts.
"""

from __future__ import annotations

COMPONENTS = ("base_prompt", "inference", "injected_context", "miss_penalty", "accumulation")


def _empty() -> dict:
    return {**{k: 0 for k in COMPONENTS}, "total": 0, "calls": 0}


def split(meta: dict) -> dict:
    usage = meta.get("usage") or {}
    prompt = int(usage.get("prompt_tokens", 0))
    completion = int(usage.get("completion_tokens", 0))
    stripped = int(meta.get("stripped_prompt_tokens", prompt))
    history = int(meta.get("history_tokens", 0))
    if stripped > prompt:
        raise ValueError(f"stripped prompt ({stripped}) is longer than the full prompt ({prompt})")
    out = {k: 0 for k in COMPONENTS}
    if meta.get("missed"):
        # The whole call was wasted: its answer was rejected and the rule parser answered instead.
        out["miss_penalty"] = prompt + completion
    else:
        out["injected_context"] = prompt - stripped
        out["accumulation"] = history
        out["base_prompt"] = stripped - history
        out["inference"] = completion
    return out


def attribute(steps: list[dict]) -> dict:
    by_node: dict[str, dict] = {}
    total = _empty()
    for s in steps:
        if s.get("kind") != "model":
            continue
        meta = s.get("meta") or {}
        parts = split(meta)
        node = by_node.setdefault(meta.get("node", s.get("name", "model")), _empty())
        for bucket in (node, total):
            for k, v in parts.items():
                bucket[k] += v
            bucket["total"] += sum(parts.values())
            bucket["calls"] += 1
    return {"by_node": by_node, "total": total}


def merge(tcas: list[dict]) -> dict:
    by_node: dict[str, dict] = {}
    total = _empty()
    for t in tcas:
        for node, parts in t["by_node"].items():
            dst = by_node.setdefault(node, _empty())
            for k in (*COMPONENTS, "total", "calls"):
                dst[k] += parts[k]
        for k in (*COMPONENTS, "total", "calls"):
            total[k] += t["total"][k]
    return {"by_node": by_node, "total": total}
