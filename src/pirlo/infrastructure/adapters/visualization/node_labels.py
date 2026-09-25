# src/pirlo/infrastructure/adapters/visualization/node_labels.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import PlayBlueprint


def build_vertex_labels(blueprint: PlayBlueprint) -> dict[str, str]:
    """Maps each node_id to its display label, marking mapped (fan-out) nodes."""
    return {
        node.node_id: (
            f"{node.display_name} [map]" if node.is_mapped else node.display_name
        )
        for node in blueprint.nodes
    }
