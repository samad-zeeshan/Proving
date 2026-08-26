"""Saved runs as gzipped JSON lines, one simulated conversation per line."""

from __future__ import annotations

import gzip
import json
from pathlib import Path


def write_runs(path: Path, runs: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in runs)
    # mtime=0 keeps the gzip header fixed, so an unchanged run set gives an unchanged file in git.
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
        gz.write(body.encode("utf-8"))


def read_runs(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
