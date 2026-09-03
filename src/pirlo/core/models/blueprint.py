# src/pirlo/core/models/blueprint.py
from __future__ import annotations

from dataclasses import dataclass, field
from pydantic import BaseModel


class PlaybookOutput(BaseModel):
    """Base class for all strongly-typed playbook output payloads."""

    pass


# Union type for strongly-typed static kwarg values
type ParameterValue = (
    str
    | int
    | float
    | bool
    | PlaybookOutput
    | list[PlaybookOutput]
    | dict[str, PlaybookOutput]
    | None
)


class BlueprintError(Exception):
    """Raised when Blueprint tracing or DAG graph resolution encounters an error."""


@dataclass(frozen=True)
class ParamBinding:
    """Data flowing from an upstream node field to a downstream param."""

    source_node_id: str
    source_field: str


@dataclass
class BlueprintNode:
    """Engine-agnostic representation of a Playbook node in a DAG."""

    node_id: str
    playbook_name: str
    static_kwargs: dict[str, ParameterValue] = field(default_factory=dict)
    param_bindings: dict[str, ParamBinding] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class PlaybookBlueprint:
    """The complete engine-agnostic blueprint of a Playbook DAG."""

    name: str
    entry_playbook: str
    output_node_id: str | None = None
    nodes: list[BlueprintNode] = field(default_factory=list)


@dataclass(frozen=True)
class ProxyRef:
    """Symbolic reference captured during dry-run tracing."""

    node_id: str
    field: str


class SymbolicProxy:
    """Interprets property access (e.g. player_login.ball.auth_token or player_login.auth_token) as a ProxyRef."""

    def __init__(self, node_id: str) -> None:
        self._node_id: str = node_id

    @property
    def ball(self) -> SymbolicProxy:
        """Football metaphor alias for accessing output payload fields."""
        return self

    def __getattr__(self, name: str) -> ProxyRef:
        if name.startswith("_"):
            raise AttributeError(name)
        return ProxyRef(node_id=self._node_id, field=name)
