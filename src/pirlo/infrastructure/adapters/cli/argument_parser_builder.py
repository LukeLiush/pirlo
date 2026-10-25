from __future__ import annotations

import argparse
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pirlo.core.models.parameters import LinkParameter, Parameter
from pirlo.core.ports.play import Play
from pirlo.infrastructure.adapters.cli.compact_help_formatter import (
    CompactHelpFormatter,
)

logger = logging.getLogger(__name__)


def _extract_signature_parameters(
    target_fn: Callable[..., Any],
) -> list[dict[str, Any]]:
    """Extract type annotations, defaults, and Annotated metadata from a function signature."""
    sig = inspect.signature(target_fn)
    try:
        type_hints = get_type_hints(target_fn, include_extras=True)
    except Exception:  # noqa: BLE001
        type_hints = {}

    params_metadata: list[dict[str, Any]] = []

    for idx, (name, param) in enumerate(sig.parameters.items()):
        if name in ("self", "self_inst", "prepared_run", "worker_fn") or (
            idx == 0 and name.startswith("self")
        ):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        param_type: Any = type_hints.get(name, param.annotation)
        default_val: Any = (
            param.default if param.default is not inspect.Parameter.empty else None
        )

        if param_type is inspect.Parameter.empty:
            if default_val is not None and type(default_val) is not object:
                param_type = type(default_val)
            else:
                param_type = str

        parameter_meta: Parameter | None = None

        if get_origin(param_type) is Annotated:
            args = get_args(param_type)
            param_type = args[0]
            for arg in args[1:]:
                if isinstance(arg, Parameter):
                    parameter_meta = arg
                    break

        raw_type = param_type
        origin = get_origin(param_type)
        if (
            origin is not list
            and origin is not dict
            and hasattr(param_type, "__args__")
            and type(None) in get_args(param_type)
        ):
            non_none = [a for a in get_args(param_type) if a is not type(None)]
            if non_none:
                param_type = non_none[0]

        params_metadata.append(
            {
                "name": name,
                "type": param_type,
                "raw_type": raw_type,
                "default": default_val,
                "help": parameter_meta.help if parameter_meta else None,
                "short": parameter_meta.short if parameter_meta else None,
                "env_name": parameter_meta.env_name if parameter_meta else None,
                "is_link": isinstance(parameter_meta, LinkParameter),
                "parameter_meta": parameter_meta,
            }
        )

    return params_metadata


class ArgumentParserBuilder:
    """Builds an ``argparse.ArgumentParser`` for a play, bubbling up its upstream plays' parameters.

    ``parameters`` is the single list behind both ``--help`` and run resolution.
    """

    def __init__(self, play_cls: type[Play[Any]]) -> None:
        self._play_cls: type[Play[Any]] = play_cls
        self._description: str | None = (
            getattr(play_cls, "playbook_description", None)
            or getattr(play_cls, "play_description", None)
            or play_cls.__doc__
        )
        self._upstream_params_by_cls: dict[type[Any], list[dict[str, Any]]] = {}
        self._parameters: list[dict[str, Any]] = _extract_signature_parameters(
            play_cls.execute
        )
        self._discover_upstream_parameters(play_cls)

    def _discover_upstream_parameters(self, target_cls: type[Any]) -> None:
        visited: set[type[Any]] = {target_cls}
        queue: list[type[Any]] = [
            req.play_cls for req in target_cls.get_upstream_requirements().values()
        ]
        while queue:
            upstream_cls = queue.pop(0)
            if upstream_cls in visited:
                continue
            visited.add(upstream_cls)

            fn = getattr(upstream_cls, "execute", None)
            if fn:
                upstream_params = _extract_signature_parameters(fn)
                self._upstream_params_by_cls[upstream_cls] = upstream_params
                for p in upstream_params:
                    # Bubble parameter to self._parameters if not already present
                    if not any(
                        existing["name"] == p["name"] for existing in self._parameters
                    ):
                        p_copy = dict(p)
                        p_copy["source_cls"] = upstream_cls
                        self._parameters.append(p_copy)

            if hasattr(upstream_cls, "get_upstream_requirements"):
                for req in upstream_cls.get_upstream_requirements().values():
                    if req.play_cls not in visited:
                        queue.append(req.play_cls)

    @property
    def parameters(self) -> list[dict[str, Any]]:
        return self._parameters

    def build_parser(
        self,
        prog_name: str,
        epilog_text: str | None = None,
    ) -> argparse.ArgumentParser:
        description = self._description or ""
        from pirlo.core.services.blueprint_extractor import BlueprintExtractor
        from pirlo.infrastructure.adapters.visualization.renderer_factory import (
            BlueprintRendererFactory,
        )

        try:
            blueprint = BlueprintExtractor.extract_from_play(self._play_cls)
            renderer = BlueprintRendererFactory.get_renderer()
            dag_text = renderer.render(blueprint)
            if dag_text:
                description = (
                    f"{description}\n{dag_text}" if description else dag_text.strip()
                )
        except Exception as err:  # noqa: BLE001
            logger.warning(
                "Could not render workflow DAG in help for %s: %s",
                prog_name,
                err,
            )

        parser = argparse.ArgumentParser(
            prog=prog_name,
            description=description,
            epilog=epilog_text,
            formatter_class=CompactHelpFormatter,
        )
        added_flags: set[str] = set()

        if self._upstream_params_by_cls:
            target_name = (
                getattr(self._play_cls, "play_name", None) or self._play_cls.__name__
            )
            target_group = parser.add_argument_group(
                f"Target Play Options ({target_name})"
            )
            target_params = _extract_signature_parameters(self._play_cls.execute)
            for param in target_params:
                self._add_argument(target_group, param, added_flags)

            for upstream_cls, up_params in self._upstream_params_by_cls.items():
                upstream_name = getattr(
                    upstream_cls, "play_name", upstream_cls.__name__
                )
                upstream_group = parser.add_argument_group(
                    f"Upstream Dependency Options ({upstream_name})"
                )
                for param in up_params:
                    self._add_argument(upstream_group, param, added_flags)
        else:
            for param in self._parameters:
                self._add_argument(parser, param, added_flags)

        parser.add_argument(
            "-l",
            "--log",
            action="store_true",
            help="Stream structured telemetry and logs directly to terminal stdout",
        )
        parser.add_argument(
            "-f",
            "--force",
            "--no-cache",
            dest="force",
            action="store_true",
            default=False,
            help="Bypass cached results and force complete re-execution",
        )
        parser.add_argument(
            "-r",
            "--routine",
            type=str,
            default=None,
            metavar="CRON",
            help=(
                "Execution routine as a cron expression (e.g. '0 9 * * *') "
                "or preset ('hourly', 'daily', 'weekly', 'monthly'). "
                "Omit to run once immediately."
            ),
        )
        parser.add_argument(
            "--orchestrator",
            type=str,
            default=None,
            metavar="LINK",
            help="Target orchestrator link name. If omitted, defaults to local ephemeral Prefect.",
        )
        return parser

    @staticmethod
    def _add_argument(
        parser: argparse.ArgumentParser | argparse._ArgumentGroup,
        param_info: dict[str, Any],
        added_flags: set[str],
    ) -> None:
        name = param_info["name"]
        flag = f"--{name.replace('_', '-')}"
        if flag in added_flags:
            return
        added_flags.add(flag)

        kwargs: dict[str, Any] = {
            "help": param_info.get("help"),
            "default": argparse.SUPPRESS,
        }

        type_func = param_info.get("type", str)
        origin = get_origin(type_func)
        if origin is list:
            is_list = True
            type_args = get_args(type_func)
            type_func = type_args[0] if type_args else str
        else:
            is_list = False
            if (
                origin is not None
                and hasattr(type_func, "__args__")
                and type(None) in get_args(type_func)
            ):
                non_none_args = [
                    arg for arg in get_args(type_func) if arg is not type(None)
                ]
                type_func = non_none_args[0] if non_none_args else str

        if type_func is bool:
            kwargs["action"] = "store_true"
        else:
            if param_info.get("is_link") or (
                isinstance(type_func, type)
                and not issubclass(type_func, (str, int, float, Path))
            ):
                kwargs["type"] = str
            else:
                kwargs["type"] = type_func if callable(type_func) else str

            if is_list:
                kwargs["nargs"] = "*"

        short = param_info.get("short")
        if short:
            parser.add_argument(short, flag, **kwargs)
        else:
            parser.add_argument(flag, **kwargs)
