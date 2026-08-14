from __future__ import annotations

import argparse
from typing import Any

from pirlo.core.models.parameters import Parameter, Parameterizable
from pirlo.infrastructure.services.parameter_provider import discover_parameters


class ArgumentParserBuilder:
    """Builds the ``argparse`` parser for a playbook class's parameters.

    Single responsibility: translate declared ``Parameter`` objects into
    argparse arguments. Parameters are discovered once at construction.
    """

    def __init__(self, parameterizable_class: type[Parameterizable]) -> None:
        self._parameterizable_class = parameterizable_class
        self._parameters: list[Parameter] = discover_parameters(parameterizable_class)

    def build_parser(
        self,
        playbook_name: str,
        epilog_text: str | None = None,
    ) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=f"pirlo {playbook_name}",
            description=self._parameterizable_class.__doc__,
            epilog=epilog_text,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        added_flags: set[str] = set()
        for param in self._parameters:
            self._add_argument(parser, param, added_flags)
        return parser

    @staticmethod
    def _add_argument(
        parser: argparse.ArgumentParser,
        param: Parameter,
        added_flags: set[str],
    ) -> None:
        flag = f"--{param.name.replace('_', '-')}"
        if flag in added_flags:
            return
        added_flags.add(flag)

        kwargs: dict[str, Any] = {
            "help": param.help,
            "default": argparse.SUPPRESS,
        }

        type_func = param.type_func
        origin = getattr(type_func, "__origin__", type_func)
        is_list = origin is list
        if is_list:
            type_args = getattr(type_func, "__args__", ())
            type_func = type_args[0] if type_args else str

        if type_func is bool:
            kwargs["action"] = "store_true"
        else:
            kwargs["type"] = type_func
            if is_list:
                kwargs["nargs"] = "*"

        if param.short:
            parser.add_argument(param.short, flag, **kwargs)
        else:
            parser.add_argument(flag, **kwargs)
