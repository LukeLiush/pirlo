# src/pirlo/core/services/blueprint_extractor.py
from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from pirlo.core.models.blueprint import (
    BlueprintNode,
    ParamBinding,
    ParameterValue,
    PlayBlueprint,
    ProxyRef,
)
from pirlo.core.ports.play import MappedParameter

if TYPE_CHECKING:
    from pirlo.core.ports.play import Play


class BlueprintExtractor:
    """Extracts an engine-agnostic PlayBlueprint IR by resolving requires() dependencies."""

    @classmethod
    def extract_from_play(
        cls,
        play_cls: type[Play[object]],
        user_kwargs: dict[str, ParameterValue] | None = None,
    ) -> PlayBlueprint:
        blueprint = PlayBlueprint(
            name=play_cls.__name__,
            entry_playbook=play_cls.__name__,
        )
        visited_nodes: dict[type[Play[object]], str] = {}
        all_user_kwargs: dict[str, ParameterValue] = user_kwargs or {}

        def _resolve(
            target_play: type[Play[object]],
            step_kwargs: dict[str, ParameterValue | MappedParameter],
        ) -> str:
            if target_play in visited_nodes:
                return visited_nodes[target_play]

            node_id = f"play_{len(blueprint.nodes) + 1}_{target_play.__name__}"
            depends_on: list[str] = []
            param_bindings: dict[str, ParamBinding] = {}
            mapped_bindings: dict[str, ParamBinding] = {}
            is_mapped: bool = False

            # 1. Depth-first resolution of upstream requires() dependencies
            for field_name, req_desc in target_play.get_upstream_requirements().items():
                upstream_id = _resolve(req_desc.play_cls, req_desc.kwargs)
                if upstream_id not in depends_on:
                    depends_on.append(upstream_id)
                param_bindings[field_name] = ParamBinding(
                    source_node_id=upstream_id,
                    source_field="",
                )

            # 2. Bubble user CLI parameters matching this play's execute signature
            fn = getattr(target_play, "execute", None)
            node_user_kwargs: dict[str, ParameterValue] = {}
            if fn:
                sig = inspect.signature(fn)
                for parameter_name, parameter_value in all_user_kwargs.items():
                    if parameter_name in sig.parameters:
                        node_user_kwargs[parameter_name] = parameter_value

            effective_step_kwargs = {**node_user_kwargs, **step_kwargs}

            # 3. Dynamic fan-in and parameter bindings
            static_kwargs: dict[str, ParameterValue] = {}
            mapped_static_kwargs: list[str] = []
            for parameter_name, parameter_value in effective_step_kwargs.items():
                if isinstance(parameter_value, MappedParameter):
                    is_mapped = True
                    target_val = parameter_value.target
                    if isinstance(target_val, ProxyRef):
                        mapped_bindings[parameter_name] = ParamBinding(
                            source_node_id=target_val.node_id,
                            source_field=target_val.field,
                        )
                        if target_val.node_id not in depends_on:
                            depends_on.append(target_val.node_id)
                    else:
                        static_kwargs[parameter_name] = target_val
                        mapped_static_kwargs.append(parameter_name)
                elif isinstance(parameter_value, ProxyRef):
                    param_bindings[parameter_name] = ParamBinding(
                        source_node_id=parameter_value.node_id,
                        source_field=parameter_value.field,
                    )
                    if parameter_value.node_id not in depends_on:
                        depends_on.append(parameter_value.node_id)
                else:
                    static_kwargs[parameter_name] = parameter_value

            node = BlueprintNode(
                node_id=node_id,
                playbook_name=target_play.__name__,
                static_kwargs=static_kwargs,
                param_bindings=param_bindings,
                mapped_bindings=mapped_bindings,
                mapped_static_kwargs=mapped_static_kwargs,
                is_mapped=is_mapped
                or len(mapped_bindings) > 0
                or len(mapped_static_kwargs) > 0,
                depends_on=depends_on,
            )
            blueprint.nodes.append(node)
            visited_nodes[target_play] = node_id
            return node_id

        terminal_id = _resolve(play_cls, {})
        blueprint.output_node_id = terminal_id
        return blueprint

    @classmethod
    def extract(
        cls,
        play_cls: type[Play[object]],
        user_kwargs: dict[str, ParameterValue] | None = None,
    ) -> PlayBlueprint:
        return cls.extract_from_play(play_cls, user_kwargs=user_kwargs)
