"""Value object for CLI arguments split at the orchestrator delimiter."""

from __future__ import annotations

from dataclasses import dataclass


def ensure_canonical_orchestrator_delimiter(
    raw_arguments: list[str], default_orchestrator_name: str = "prefect"
) -> list[str]:
    """
    Ensures '-- <default_orchestrator_name>' is attached to raw CLI arguments if '--' is omitted.

    Examples:
      ['--task', 'Search'] -> ['--task', 'Search', '--', 'prefect']
      ['--task', 'Search', '--', 'prefect'] -> unchanged
    """
    if "--" not in raw_arguments:
        return raw_arguments + ["--", default_orchestrator_name]
    return raw_arguments


@dataclass(frozen=True)
class PlaybookInvocation:
    """CLI arguments split at the ``--`` orchestrator delimiter.

    ``playbook_args`` are the tokens before ``--`` (parsed by the playbook's
    argparse parser); ``orchestrator_args`` are the tokens after it (passed
    through to the orchestrator, e.g. prefect).

    Construct via :meth:`from_raw`, which normalizes a raw argument list by
    ensuring a canonical ``--`` delimiter is present before splitting.
    """

    playbook_args: list[str]
    orchestrator_args: list[str]

    @classmethod
    def from_raw(
        cls,
        raw_arguments: list[str],
        *,
        default_orchestrator_name: str,
    ) -> PlaybookInvocation:
        """Normalize and split a raw argument list.

        If ``raw_arguments`` omits the ``--`` delimiter, a canonical one is
        inserted (defaulting the orchestrator to ``default_orchestrator_name``)
        before splitting.
        """
        canonical = ensure_canonical_orchestrator_delimiter(
            raw_arguments, default_orchestrator_name=default_orchestrator_name
        )
        split_index = canonical.index("--")
        return cls(
            playbook_args=canonical[:split_index],
            orchestrator_args=canonical[split_index + 1 :],
        )
