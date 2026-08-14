import sys
from unittest.mock import patch

from pirlo.infrastructure.adapters.cli.entrypoint import main


def test_cli_orchestrator_playbook_routing():
    test_args = [
        "pirlo",
        "autopass",
        "--task",
        "Search Google",
        "--",
        "prefect",
        "--help",
    ]

    with (
        patch.object(sys, "argv", test_args),
        patch("pirlo.playbooks.autopass.main.AutopassSession.cli") as mock_session_cli,
    ):
        try:
            main()
        except SystemExit:
            pass

        mock_session_cli.assert_called_once_with(playbook_name="autopass")
