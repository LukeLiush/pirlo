# src/pirlo/infrastructure/adapters/cli/compact_help_formatter.py
from __future__ import annotations

import argparse


class CompactHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Prints '-r, --routine CRON' rather than argparse's '-r CRON, --routine CRON'.

    Preserves raw description text so the rendered workflow DAG survives intact.
    Python 3.13 formats options this way natively; this keeps 3.12 consistent.
    """

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings or action.nargs == 0:
            return super()._format_action_invocation(action)
        default = self._get_default_metavar_for_optional(action)
        args_string = self._format_args(action, default)
        return f"{', '.join(action.option_strings)} {args_string}"
