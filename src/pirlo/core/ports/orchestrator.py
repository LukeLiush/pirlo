from __future__ import annotations

import argparse
from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from pirlo.core.models.link import LlmLink
from pirlo.core.models.parameters import Parameter, Parameterizable

if TYPE_CHECKING:
    from pirlo.core.models.run import PreparedRun



class AutopassExecutionOptions(BaseModel):
    """Explicitly typed execution options for Autopass sessions."""

    playmaker: LlmLink = Field(description="LlmLink object for decision brain")
    analyst: LlmLink = Field(
        description="LlmLink object for DOM analysis & selector repair"
    )
    use_vision: bool = Field(default=False, description="Enable vision capabilities")
    max_failures: int = Field(
        default=5, description="Max failure attempts before stopping"
    )
    retry_delay: int = Field(default=10, description="Retry delay in seconds")
    generate_gif: bool = Field(
        default=False, description="Generate execution GIF artifact"
    )
    cron: str | None = Field(
        default=None,
        description="Optional cron schedule expression (e.g. '0 9 * * *')",
    )


class TaskOrchestrator(Parameterizable):
    @classmethod
    def _add_parameter_to_parser(
            cls, parser: argparse.ArgumentParser, attr_name: str, attr_val: Parameter
    ) -> None:
        flag = f"--{attr_name.replace('_', '-')}"
        if flag in parser._option_string_actions:
            return

        kwargs: dict[str, Any] = {
            "help": attr_val.help,
            "default": argparse.SUPPRESS,
        }

        type_func = attr_val.type_func
        is_list = False
        origin = getattr(type_func, "__origin__", type_func)

        if origin is list:
            is_list = True
            type_args = getattr(type_func, "__args__", ())
            type_func = type_args[0] if type_args else str

        if type_func == bool:
            kwargs["action"] = "store_true"
        else:
            kwargs["type"] = type_func
            if is_list:
                kwargs["nargs"] = "*"

        if attr_val.short:
            parser.add_argument(attr_val.short, flag, **kwargs)
        else:
            parser.add_argument(flag, **kwargs)

    @classmethod
    def parse_cli_options(
            cls,
            playbook_name: str,
            orchestrator_flags: list[str],
    ) -> dict[str, Any]:
        """
        Parses CLI flags for this orchestrator backend.

        :param playbook_name: Name of the active playbook (e.g. "autopass", "login").
        :param orchestrator_flags: CLI flags passed after '-- <orchestrator_name>' (e.g. ["--server-url", "http://..."]).
        :return: Dictionary of parsed orchestrator options.
        """
        program_header = f"pirlo {playbook_name} -- {cls.name}"
        parser = argparse.ArgumentParser(
            prog=program_header,
            description=f"{cls.name.capitalize()} Task Orchestrator Options",
        )

        for attr_name in dir(cls):
            attr_val = getattr(cls, attr_name)
            if isinstance(attr_val, Parameter):
                cls._add_parameter_to_parser(parser, attr_name, attr_val)

        flags = list(orchestrator_flags)
        if flags and flags[0].lower() == cls.name.lower():
            flags = flags[1:]

        parsed_arguments = parser.parse_args(flags)

        return {
            attr_name: getattr(parsed_arguments, attr_name)
            for attr_name in dir(cls)
            if isinstance(getattr(cls, attr_name), Parameter)
               and hasattr(parsed_arguments, attr_name)
        }

    @abstractmethod
    async def execute(
            self,
            task: str,
            prepared_run: PreparedRun,
            worker_fn: Callable[[], Any],
            schedule: str | None = None,
    ) -> Any:
        """
        Executes an orchestrated workflow.
        Wraps pitch worker_fn in orchestration context (status tracking, logging, cron schedules).
        """
