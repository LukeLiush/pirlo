# src/pirlo/infrastructure/adapters/visualization/phart_renderer.py
from __future__ import annotations

from typing import TYPE_CHECKING

from pirlo.core.ports.blueprint_renderer import BlueprintRenderer

if TYPE_CHECKING:
    from pirlo.core.models.blueprint import BlueprintNode, PlayBlueprint


class PhartBlueprintRenderer(BlueprintRenderer):
    """Renders PlayBlueprint as 2D ASCII/Unicode DAG using NetworkX and PHART."""

    def render(self, blueprint: PlayBlueprint) -> str:
        if not blueprint.nodes:
            return ""

        if len(blueprint.nodes) == 1:
            return f"\nWorkflow DAG:\n[{blueprint.nodes[0].playbook_name}]\n"

        import networkx as nx
        from phart import ASCIIRenderer

        g = nx.DiGraph()
        node_by_id: dict[str, BlueprintNode] = {n.node_id: n for n in blueprint.nodes}
        mapped_ghost_nodes: dict[str, str] = {}

        for node in blueprint.nodes:
            if node.is_mapped:
                mapped_ghost_nodes[node.node_id] = f"··· ({node.playbook_name} mapped)"

        for node in blueprint.nodes:
            g.add_node(node.playbook_name)
            if node.node_id in mapped_ghost_nodes:
                g.add_node(mapped_ghost_nodes[node.node_id])

            for parent_id in node.depends_on:
                parent_node = node_by_id.get(parent_id)
                if parent_node:
                    g.add_edge(parent_node.playbook_name, node.playbook_name)

                    # Fan-out: edge from parent to mapped ghost node
                    if node.node_id in mapped_ghost_nodes:
                        g.add_edge(
                            parent_node.playbook_name,
                            mapped_ghost_nodes[node.node_id],
                        )

                    # Fan-in: edge from parent's ghost node to this downstream node
                    if parent_id in mapped_ghost_nodes:
                        g.add_edge(
                            mapped_ghost_nodes[parent_id],
                            node.playbook_name,
                        )

        renderer = ASCIIRenderer(g)
        raw_dag = renderer.render().rstrip()
        return f"\nWorkflow DAG:\n{raw_dag}\n"
