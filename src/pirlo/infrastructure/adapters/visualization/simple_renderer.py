# src/pirlo/infrastructure/adapters/visualization/simple_renderer.py
from __future__ import annotations

from typing import TYPE_CHECKING

from pirlo.core.ports.blueprint_renderer import BlueprintRenderer
from pirlo.infrastructure.adapters.visualization.node_labels import (
    build_vertex_labels,
)

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import PlayBlueprint


class SimpleBlueprintRenderer(BlueprintRenderer):
    """Renders PlayBlueprint as a one-line-per-node edge list, with no layout engine."""

    def render(self, blueprint: PlayBlueprint) -> str:
        if not blueprint.nodes:
            return ""

        labels: dict[str, str] = build_vertex_labels(blueprint)
        lines: list[str] = []
        for node in blueprint.nodes:
            label = labels[node.node_id]
            if node.depends_on:
                parents = ", ".join(
                    labels.get(parent_id, parent_id) for parent_id in node.depends_on
                )
                lines.append(f"  {parents} -> {label}")
            else:
                lines.append(f"  {label}")

        rendered = "\n".join(lines)
        return f"\nWorkflow DAG:\n{rendered}\n"
