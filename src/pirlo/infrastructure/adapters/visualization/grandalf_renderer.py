# src/pirlo/infrastructure/adapters/visualization/grandalf_renderer.py
from __future__ import annotations

from typing import TYPE_CHECKING

from pirlo.core.ports.blueprint_renderer import BlueprintRenderer

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import PlayBlueprint


class GrandalfBlueprintRenderer(BlueprintRenderer):
    """Renders PlayBlueprint using Grandalf and LangChain default draw_ascii."""

    def render(self, blueprint: PlayBlueprint) -> str:
        if not blueprint.nodes:
            return ""

        if len(blueprint.nodes) == 1:
            return f"\nWorkflow DAG:\n  [{blueprint.nodes[0].display_name}]\n"

        from langchain_core.runnables.graph import Edge
        from langchain_core.runnables.graph_ascii import draw_ascii

        vertices: dict[str, str] = {
            node.node_id: (
                f"{node.display_name} [map]" if node.is_mapped else node.display_name
            )
            for node in blueprint.nodes
        }

        edges: list[Edge] = [
            Edge(source=parent_id, target=node.node_id)
            for node in blueprint.nodes
            for parent_id in node.depends_on
        ]

        rendered = draw_ascii(vertices, edges).rstrip()
        return f"\nWorkflow DAG:\n{rendered}\n"
