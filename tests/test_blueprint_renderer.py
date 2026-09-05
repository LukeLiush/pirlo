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
from pirlo.infrastructure.adapters.visualization.renderer_factory import (
    BlueprintRendererFactory,
)
from pirlo.playbooks.autopass.main import AutopassPlay


def test_grandalf_renderer_empty_blueprint():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(name="empty", entry_playbook="empty", nodes=[])
    assert renderer.render(bp) == ""


def test_grandalf_renderer_single_node_fallback():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="single",
        entry_playbook="SinglePlay",
        nodes=[BlueprintNode(node_id="n1", playbook_name="SinglePlay")],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "[SinglePlay]" in res


def test_grandalf_renderer_single_node_with_play_name():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="single",
        entry_playbook="single_cmd",
        nodes=[
            BlueprintNode(
                node_id="n1", playbook_name="SinglePlay", play_name="single_cmd"
            )
        ],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "[single_cmd]" in res


def test_grandalf_renderer_mapped_pipeline_with_play_names():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="mapped_flow",
        entry_playbook="final_cmd",
        nodes=[
            BlueprintNode(
                node_id="n1", playbook_name="FirstPlay", play_name="first_cmd"
            ),
            BlueprintNode(
                node_id="n2",
                playbook_name="MappedPlay",
                play_name="mapped_cmd",
                depends_on=["n1"],
                is_mapped=True,
            ),
            BlueprintNode(
                node_id="n3",
                playbook_name="FinalPlay",
                play_name="final_cmd",
                depends_on=["n2"],
            ),
        ],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "first_cmd" in res
    assert "mapped_cmd [map]" in res
    assert "final_cmd" in res


def test_grandalf_renderer_multi_parent_join():
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="multi_parent",
        entry_playbook="join_cmd",
        nodes=[
            BlueprintNode(node_id="n1", playbook_name="BranchA", play_name="branch_a"),
            BlueprintNode(node_id="n2", playbook_name="BranchB", play_name="branch_b"),
            BlueprintNode(
                node_id="n3",
                playbook_name="JoinPlay",
                play_name="join_cmd",
                depends_on=["n1", "n2"],
            ),
        ],
    )
    res = renderer.render(bp)
    assert "Workflow DAG:" in res
    assert "branch_a" in res
    assert "branch_b" in res
    assert "join_cmd" in res


def test_renderer_factory_defaults_and_substitution():
    default_renderer = BlueprintRendererFactory.get_renderer()
    assert isinstance(default_renderer, GrandalfBlueprintRenderer)

    grandalf_renderer = BlueprintRendererFactory.get_renderer("grandalf")
    assert isinstance(grandalf_renderer, GrandalfBlueprintRenderer)

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


def test_argument_parser_builder_includes_dag_and_play_names_in_help():
    builder = ArgumentParserBuilder(AutopassPlay)
    parser = builder.build_parser("autopass")
    help_text = parser.format_help()

    assert "Workflow DAG:" in help_text
    assert "autopass_decompose" in help_text
    assert "autopass_execute_subtask [map]" in help_text
    assert "autopass" in help_text
    assert "Target Play Options (autopass)" in help_text
    assert "Upstream Dependency Options (autopass_execute_subtask)" in help_text
    assert "Upstream Dependency Options (autopass_decompose)" in help_text
