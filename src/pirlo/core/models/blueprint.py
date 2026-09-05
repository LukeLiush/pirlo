# src/pirlo/core/models/blueprint.py
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


class PlayOutput(BaseModel):
    """Base class for all strongly-typed play output payloads."""


from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pirlo.core.models.link import LlmLink
    from pirlo.core.ports.blueprint_renderer import BlueprintRenderer
    from pirlo.core.ports.play import MappedParameter

type ScalarValue = (
    str | int | float | bool | Path | LlmLink | PlayOutput | ProxyRef | MappedParameter
)

# Union type for strongly-typed static kwarg values
type ParameterValue = (
    ScalarValue
    | list[ScalarValue]
    | list[dict[str, ScalarValue]]
    | dict[str, ScalarValue]
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
    mapped_bindings: dict[str, ParamBinding] = field(default_factory=dict)
    mapped_static_kwargs: list[str] = field(default_factory=list)
    is_mapped: bool = False
    depends_on: list[str] = field(default_factory=list)

    def render_ascii(self) -> str:
        """Renders ASCII diagnostic summary of this single node."""
        bindings = ", ".join(
            f"{k} ◄─ {b.source_node_id}.{b.source_field}"
            for k, b in self.param_bindings.items()
        )
        deps = ", ".join(self.depends_on) or "none"
        mapped_flag = " [MAPPER/FAN-OUT]" if self.is_mapped else ""
        return (
            f"Node: {self.node_id} ({self.playbook_name}){mapped_flag}\n"
            f"  Kwargs:   {self.static_kwargs}\n"
            f"  Bindings: {bindings or 'none'}\n"
            f"  Depends:  [{deps}]"
        )


@dataclass
class PlayBlueprint:
    """The complete engine-agnostic blueprint of a Play DAG."""

    name: str
    entry_playbook: str
    output_node_id: str | None = None
    nodes: list[BlueprintNode] = field(default_factory=list)

    @property
    def entry_play(self) -> str:
        """Alias for entry_playbook."""
        return self.entry_playbook

    def render_ascii(self) -> str:
        """Renders ASCII diagnostic summary of the complete DAG blueprint."""
        header = (
            f"=== [PlayBlueprint: {self.name}] ===\n"
            f"Output Target: {self.output_node_id or 'none'}\n"
            f"Total Nodes:   {len(self.nodes)}\n" + "-" * 45
        )
        nodes_str = "\n\n".join(node.render_ascii() for node in self.nodes)
        return f"{header}\n{nodes_str}\n" + "=" * 45

    def render_blueprint_ascii(self) -> str:
        """Alias for render_ascii()."""
        return self.render_ascii()

    def to_ascii(self, renderer: BlueprintRenderer | None = None) -> str:
        """Renders this blueprint into a DAG visualization using the configured renderer."""
        if renderer is None:
            from pirlo.infrastructure.adapters.visualization.renderer_factory import (
                BlueprintRendererFactory,
            )

            renderer = BlueprintRendererFactory.get_renderer()
        return renderer.render(self)


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
