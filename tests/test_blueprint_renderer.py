# tests/test_blueprint_renderer.py
from __future__ import annotations

import pytest

from pirlo.core.models.blueprint import BlueprintNode, PlayBlueprint
from pirlo.core.ports.blueprint_renderer import BlueprintRenderer
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.visualization.grandalf_renderer import (
    GrandalfBlueprintRenderer,
)
from pirlo.infrastructure.adapters.visualization.phart_renderer import (
    PhartBlueprintRenderer,
)
from pirlo.infrastructure.adapters.visualization.renderer_factory import (
    BlueprintRendererFactory,
)
from pirlo.playbooks.autopass.main import AutopassPlay


def test_grandalf_renderer_empty_blueprint():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(name="empty", entry_playbook="empty", nodes=[])
    assert renderer.render(bp) == ""


def test_grandalf_renderer_single_node():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="single",
        entry_playbook="SinglePlay",
        nodes=[BlueprintNode(node_id="n1", playbook_name="SinglePlay")],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "[SinglePlay]" in res


def test_grandalf_renderer_mapped_pipeline():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="mapped_flow",
        entry_playbook="FinalPlay",
        nodes=[
            BlueprintNode(node_id="n1", playbook_name="FirstPlay"),
            BlueprintNode(
                node_id="n2",
                playbook_name="MappedPlay",
                depends_on=["n1"],
                is_mapped=True,
            ),
            BlueprintNode(
                node_id="n3",
                playbook_name="FinalPlay",
                depends_on=["n2"],
            ),
        ],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "FirstPlay" in res
    assert "MappedPlay [map]" in res
    assert "FinalPlay" in res


def test_grandalf_renderer_multi_parent_join():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="multi_parent",
        entry_playbook="JoinPlay",
        nodes=[
            BlueprintNode(node_id="n1", playbook_name="BranchA"),
            BlueprintNode(node_id="n2", playbook_name="BranchB"),
            BlueprintNode(
                node_id="n3",
                playbook_name="JoinPlay",
                depends_on=["n1", "n2"],
            ),
        ],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "BranchA" in res
    assert "BranchB" in res
    assert "JoinPlay" in res


def test_phart_renderer_empty_blueprint():
    renderer = PhartBlueprintRenderer()
    bp = PlayBlueprint(name="empty", entry_playbook="empty", nodes=[])
    assert renderer.render(bp) == ""


def test_phart_renderer_single_node():
    renderer = PhartBlueprintRenderer()
    bp = PlayBlueprint(
        name="single",
        entry_playbook="SinglePlay",
        nodes=[BlueprintNode(node_id="n1", playbook_name="SinglePlay")],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "[SinglePlay]" in res


def test_renderer_factory_defaults_and_substitution():
    default_renderer = BlueprintRendererFactory.get_renderer()
    assert isinstance(default_renderer, GrandalfBlueprintRenderer)

    grandalf_renderer = BlueprintRendererFactory.get_renderer("grandalf")
    assert isinstance(grandalf_renderer, GrandalfBlueprintRenderer)

    phart_renderer = BlueprintRendererFactory.get_renderer("phart")
    assert isinstance(phart_renderer, PhartBlueprintRenderer)

    with pytest.raises(ValueError, match="Unknown blueprint renderer 'unknown'"):
        BlueprintRendererFactory.get_renderer("unknown")


def test_solid_renderer_substitution_on_blueprint():
    class CustomMockRenderer(BlueprintRenderer):
        def render(self, blueprint: PlayBlueprint) -> str:
            return f"MOCK_RENDERED:{blueprint.name}"

    bp = PlayBlueprint(name="TestBP", entry_playbook="TestBP", nodes=[])
    custom_renderer = CustomMockRenderer()
    # Verifies LSP / DIP substitution
    assert bp.to_ascii(renderer=custom_renderer) == "MOCK_RENDERED:TestBP"


def test_argument_parser_builder_includes_dag_in_help():
    builder = ArgumentParserBuilder(AutopassPlay)
    parser = builder.build_parser("autopass")
    help_text = parser.format_help()

    assert "Workflow DAG:" in help_text
    assert "DecomposeTaskPlay" in help_text
    assert "ExecuteSubtaskPlay [map]" in help_text
    assert "AutopassPlay" in help_text
