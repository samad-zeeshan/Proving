"""What the core expects from a client adapter. Adapters implement it, the core never imports them.

Adding a client means writing one adapter module and one scenario folder. Nothing here changes.
"""

from __future__ import annotations

from typing import Callable, Protocol

from .customer.base import AgentTurn
from .scenarios.schema import Scenario
from .toolsim.proxy import ErrorFactory, Proxy


class Session(Protocol):
    def send(self, text: str) -> AgentTurn: ...

    def final_state(self) -> dict: ...


class Adapter(Protocol):
    name: str
    # The backend a scenario runs on when nothing else is asked for: "synth" or "live".
    default_backend: str

    def versions(self) -> dict[str, dict]: ...

    def frozen_config(self, version: str) -> dict: ...

    def phrasebook(self) -> dict: ...

    def builders(self) -> dict[str, Callable]: ...

    def errors(self) -> ErrorFactory: ...

    def session(self, scenario: Scenario, version: str, proxy: Proxy) -> Session: ...
