"""Where saved runs live, and a checkpoint so a two-hour model run survives an interruption."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .toolsim import trajectory

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "eval" / "runs"


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", text).strip("-")


def run_path(client: str, version: str, which: str = "all", customer: str = "rules") -> Path:
    name = slug(version)
    if which != "all":
        name += f".{slug(which)}"
    if customer != "rules":
        name += f".{customer}-customer"
    return RUNS / client / f"{name}.jsonl.gz"


class Checkpoint:
    """Appends each finished run to a plain JSONL file, then packs them into the gzip file at the end."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.partial = self.path.with_name(self.path.name.replace(".jsonl.gz", ".partial.jsonl"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def done(self) -> dict[str, dict]:
        if not self.partial.exists():
            return {}
        runs = {}
        for line in self.partial.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                runs[r["scenario"]] = r
        return runs

    def add(self, run: dict) -> None:
        with self.partial.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(run, ensure_ascii=False, sort_keys=True) + "\n")

    def finish(self, order: list[str]) -> list[dict]:
        done = self.done()
        runs = [done[s] for s in order if s in done]
        trajectory.write_runs(self.path, runs)
        self.partial.unlink(missing_ok=True)
        return runs


def load_runs(path: Path) -> list[dict]:
    return trajectory.read_runs(path)
