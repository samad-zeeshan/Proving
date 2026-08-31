"""Find a client checkout, put it on the import path and read the commit it is at."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PINS = json.loads((REPO / "clients.json").read_text(encoding="utf-8"))


def client_root(name: str) -> Path:
    pin = PINS[name]
    # CI checks the clients out under clients/ and says so through the env var. Locally the
    # sibling folders from clients.json are used.
    root = Path(os.environ.get(pin["env"]) or (REPO / pin["local"])).resolve()
    if not root.exists():
        raise FileNotFoundError(f"{name} checkout not found at {root}; set {pin['env']}")
    return root


def ensure_importable(name: str) -> Path:
    path = str((client_root(name) / PINS[name]["import_path"]).resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    return client_root(name)


def client_sha(name: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(client_root(name)), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def file_hash(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        # Line endings differ between a Windows checkout and CI, so hash the text with LF.
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def text_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]
