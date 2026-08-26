"""Record, replay or synthesize every boundary an agent crosses, with a step index on each.

A boundary is a tool call, a model call or a customer turn. Replay serves them from a saved run and
fails loudly at the first step where the new code asks for something different. Cut-point replay
(arXiv 2609.20625) serves steps before k from the record and runs the rest live.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

KINDS = ("tool", "model", "customer")


class ReplayDivergence(Exception):
    def __init__(self, step: int, expected: dict | None, got: dict, reason: str = "") -> None:
        self.step, self.expected, self.got = step, expected, got
        super().__init__(f"step {step}: {reason or 'the new code asked for something else'}: "
                         f"expected {expected}, got {got}")


class NoSynthesizer(Exception):
    pass


class RecordedError(Exception):
    """Raised on replay for an error whose original type the adapter did not register."""

    def __init__(self, type_name: str, message: str) -> None:
        super().__init__(f"{type_name}: {message}")
        self.type_name = type_name


class ErrorFactory:
    def __init__(self, types: dict[str, Callable[[str], BaseException]] | None = None) -> None:
        self.types = types or {}

    def __call__(self, type_name: str, message: str) -> BaseException:
        make = self.types.get(type_name)
        return make(message) if make else RecordedError(type_name, message)


@dataclass
class Envelope:
    step: int
    kind: str
    name: str
    args: dict
    out: Any = None
    error: dict | None = None
    ms: float = 0.0
    source: str = "live"
    meta: dict = field(default_factory=dict)

    def key(self) -> dict:
        return {"kind": self.kind, "name": self.name, "args": self.args}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Envelope":
        return cls(**d)


def jsonable(obj: Any) -> Any:
    # Records and live answers go through the same JSON round trip, so an agent sees identical
    # types (lists, not tuples) whether a step was recorded or served.
    return json.loads(json.dumps(obj, default=str, ensure_ascii=False))


def _same(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


class Proxy:
    def __init__(self, *, backend: str = "live", replay: Iterable[Envelope] | None = None,
                 cut: int | None = None, errors: ErrorFactory | None = None,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        if backend not in ("live", "synth"):
            raise ValueError(f"backend must be live or synth, not {backend!r}")
        self.backend = backend
        self.record = list(replay) if replay is not None else None
        self.cut = cut
        self.errors = errors or ErrorFactory()
        self.clock = clock
        self.log: list[Envelope] = []
        self.sync_mismatches = 0

    @property
    def mode(self) -> str:
        if self.record is None:
            return "synthesize" if self.backend == "synth" else "record"
        return "replay" if self.cut is None else "cut"

    def _serving(self, step: int) -> bool:
        return self.record is not None and (self.cut is None or step < self.cut)

    def _execute(self, kind: str, name: str, live: Callable[[], Any],
                 synth: Callable[[], Any] | None) -> Callable[[], Any]:
        if kind == "tool" and self.backend == "synth":
            if synth is None:
                raise NoSynthesizer(f"no synthesizer for tool {name!r}")
            return synth
        return live

    def call(self, kind: str, name: str, args: dict, live: Callable[[], Any],
             synth: Callable[[], Any] | None = None, meta: dict | None = None) -> Any:
        step = len(self.log)
        args = jsonable(args)
        env = Envelope(step=step, kind=kind, name=name, args=args, meta=dict(meta or {}))
        if self._serving(step):
            if step >= len(self.record):
                raise ReplayDivergence(step, None, env.key(), "a call beyond the record")
            rec = self.record[step]
            if not (rec.kind == kind and rec.name == name and _same(rec.args, args)):
                raise ReplayDivergence(step, rec.key(), env.key())
            env.out, env.error, env.ms, env.source = copy.deepcopy(rec.out), rec.error, rec.ms, "served"
            env.meta = {**copy.deepcopy(rec.meta), **env.meta}
            if self.cut is not None and kind == "tool":
                self._sync(env, self._execute(kind, name, live, synth))
            self.log.append(env)
            if env.error:
                raise self.errors(env.error["type"], env.error["message"])
            return copy.deepcopy(env.out)

        fn = self._execute(kind, name, live, synth)
        env.source = "synth" if fn is synth and synth is not None and kind == "tool" else "live"
        t0 = self.clock()
        try:
            env.out = jsonable(fn())
        except Exception as exc:
            env.ms = round((self.clock() - t0) * 1000, 3)
            env.error = {"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)}
            self.log.append(env)
            raise
        env.ms = round((self.clock() - t0) * 1000, 3)
        self.log.append(env)
        return copy.deepcopy(env.out)

    def _sync(self, env: Envelope, fn: Callable[[], Any]) -> None:
        # Before the cut the answer comes from the record, but the backend still has to see the call,
        # or a hold made at step 2 would not exist when the live code confirms it at step 5.
        try:
            got, err = jsonable(fn()), None
        except Exception as exc:  # noqa: BLE001 - compared with the recorded error below
            got, err = None, f"{type(exc).__module__}.{type(exc).__qualname__}"
        want_err = env.error["type"] if env.error else None
        if err != want_err or (err is None and not _same({"o": got}, {"o": env.out})):
            env.meta["sync_mismatch"] = True
            self.sync_mismatches += 1

    def finish(self) -> None:
        if self.record is None:
            return
        end = len(self.record) if self.cut is None else min(self.cut, len(self.record))
        if len(self.log) < end:
            rec = self.record[len(self.log)]
            raise ReplayDivergence(len(self.log), rec.key(), {}, "a recorded call the new code never made")
