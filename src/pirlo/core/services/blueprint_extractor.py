# src/pirlo/core/services/blueprint_extractor.py
from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from pirlo.core.models.blueprint import (
    BlueprintError,
    BlueprintNode,
    ParamBinding,
    ParameterValue,
    PlayBlueprint,
    ProxyRef,
)
from pirlo.core.ports.play import MappedParameter

if TYPE_CHECKING:
    from pirlo.core.ports.play import Play


def _get_output_type(play_cls: type[object]) -> type[object] | None:
    import typing

    from pirlo.core.models.blueprint import PlayOutput

    for base in getattr(play_cls, "__orig_bases__", ()):
        args = typing.get_args(base)
        if args and isinstance(args[0], type) and issubclass(args[0], PlayOutput):
            return args[0]
    fn = getattr(play_cls, "execute", None)
    if fn:
        sig = inspect.signature(fn)
        if isinstance(sig.return_annotation, type) and issubclass(
            sig.return_annotation, PlayOutput
        ):
            return sig.return_annotation
    return None


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

                upstream_output_type = _get_output_type(req_desc.play_cls)

                if req_desc.each:
                    if (
                        upstream_output_type
                        and hasattr(upstream_output_type, "model_fields")
                        and req_desc.each not in upstream_output_type.model_fields
                    ):
                        fields = list(upstream_output_type.model_fields.keys())
                        raise BlueprintError(
                            f"Field '{req_desc.each}' declared in each= does not exist on "
                            f"'{upstream_output_type.__name__}' of '{req_desc.play_cls.__name__}'. "
                            f"Available fields: {fields}"
                        )
                    is_mapped = True
                    mapped_bindings[field_name] = ParamBinding(
                        source_node_id=upstream_id,
                        source_field=req_desc.each,
                    )
                elif req_desc.field:
                    if (
                        upstream_output_type
                        and hasattr(upstream_output_type, "model_fields")
                        and req_desc.field not in upstream_output_type.model_fields
                    ):
                        fields = list(upstream_output_type.model_fields.keys())
                        raise BlueprintError(
                            f"Field '{req_desc.field}' declared in field= does not exist on "
                            f"'{upstream_output_type.__name__}' of '{req_desc.play_cls.__name__}'. "
                            f"Available fields: {fields}"
                        )
                    param_bindings[field_name] = ParamBinding(
                        source_node_id=upstream_id,
                        source_field=req_desc.field,
                    )
                else:
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

            registered_play_name = getattr(target_play, "play_name", None)
            node = BlueprintNode(
                node_id=node_id,
                playbook_name=target_play.__name__,
                play_name=registered_play_name,
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
