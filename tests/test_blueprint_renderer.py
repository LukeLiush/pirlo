# tests/test_blueprint_renderer.py
from __future__ import annotations

import logging

import pytest

from pirlo.core.models.blueprint import BlueprintNode, PlayBlueprint
from pirlo.core.ports.blueprint_renderer import BlueprintRenderer
from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.visualization.fallback_renderer import (
    FallbackBlueprintRenderer,
)
from pirlo.infrastructure.adapters.visualization.grandalf_renderer import (
    GrandalfBlueprintRenderer,
)
from pirlo.infrastructure.adapters.visualization.renderer_factory import (
    BlueprintRendererFactory,
)
from pirlo.infrastructure.adapters.visualization.simple_renderer import (
    SimpleBlueprintRenderer,
)
from pirlo.playbooks.demo.report_dag import SendAlertPlay


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


def test_grandalf_layout_engine_is_installed():
    """Pins the real layout engine: the edge-list fallback emits no box borders."""
    renderer = GrandalfBlueprintRenderer()
    bp = PlayBlueprint(
        name="two_node",
        entry_playbook="second_cmd",
        nodes=[
            BlueprintNode(
                node_id="n1", playbook_name="FirstPlay", play_name="first_cmd"
            ),
            BlueprintNode(
                node_id="n2",
                playbook_name="SecondPlay",
                play_name="second_cmd",
                depends_on=["n1"],
            ),
        ],
    )
    res = renderer.render(bp)
    assert "+--" in res
    assert "|" in res
    assert "->" not in res


def test_simple_renderer_edge_list():
    renderer = SimpleBlueprintRenderer()
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
    assert "  first_cmd" in res
    assert "first_cmd -> mapped_cmd [map]" in res
    assert "mapped_cmd [map] -> final_cmd" in res
    assert "+--" not in res


def test_simple_renderer_empty_blueprint():
    bp = PlayBlueprint(name="empty", entry_playbook="empty", nodes=[])
    assert SimpleBlueprintRenderer().render(bp) == ""


def test_simple_renderer_tolerates_dangling_dependency():
    """A depends_on id with no matching node degrades to the raw id, not a KeyError."""
    renderer = SimpleBlueprintRenderer()
    bp = PlayBlueprint(
        name="dangling",
        entry_playbook="second_cmd",
        nodes=[
            BlueprintNode(
                node_id="n1", playbook_name="FirstPlay", play_name="first_cmd"
            ),
            BlueprintNode(
                node_id="n2",
                playbook_name="SecondPlay",
                play_name="second_cmd",
                depends_on=["missing_node"],
            ),
        ],
    )
    assert "missing_node -> second_cmd" in renderer.render(bp)


def _two_node_blueprint() -> PlayBlueprint:
    return PlayBlueprint(
        name="two_node",
        entry_playbook="second_cmd",
        nodes=[
            BlueprintNode(
                node_id="n1", playbook_name="FirstPlay", play_name="first_cmd"
            ),
            BlueprintNode(
                node_id="n2",
                playbook_name="SecondPlay",
                play_name="second_cmd",
                depends_on=["n1"],
            ),
        ],
    )


def test_fallback_renderer_degrades_when_primary_raises(caplog):
    class BrokenRenderer(BlueprintRenderer):
        def render(self, blueprint: PlayBlueprint) -> str:
            raise ImportError("no layout engine")

    renderer = FallbackBlueprintRenderer(
        primary=BrokenRenderer(), fallback=SimpleBlueprintRenderer()
    )
    with caplog.at_level(logging.WARNING):
        res = renderer.render(_two_node_blueprint())

    assert "first_cmd -> second_cmd" in res
    assert "BrokenRenderer" in caplog.text
    assert "SimpleBlueprintRenderer" in caplog.text


def test_fallback_renderer_prefers_primary():
    renderer = FallbackBlueprintRenderer(
        primary=GrandalfBlueprintRenderer(), fallback=SimpleBlueprintRenderer()
    )
    res = renderer.render(_two_node_blueprint())
    assert "+--" in res
    assert "->" not in res


def test_renderer_factory_defaults_and_substitution():
    default_renderer = BlueprintRendererFactory.get_renderer()
    assert isinstance(default_renderer, FallbackBlueprintRenderer)
    assert isinstance(default_renderer.primary, GrandalfBlueprintRenderer)
    assert isinstance(default_renderer.fallback, SimpleBlueprintRenderer)

    assert isinstance(
        BlueprintRendererFactory.get_renderer("grandalf"), GrandalfBlueprintRenderer
    )
    assert isinstance(
        BlueprintRendererFactory.get_renderer("simple"), SimpleBlueprintRenderer
    )

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
    builder = ArgumentParserBuilder(SendAlertPlay)
    parser = builder.build_parser("demo_report_dag")
    help_text = parser.format_help()

    assert "Workflow DAG:" in help_text
    assert "demo_report_dag" in help_text
    assert "demo_download_report [map]" in help_text
    assert "Target Play Options (demo_report_dag)" in help_text
    assert "Upstream Dependency Options (demo_fetch_budget_target)" in help_text
