import sys
from unittest.mock import patch

from pirlo.infrastructure.adapters.cli.entrypoint import main


def test_cli_orchestrator_playbook_routing():
    test_args = [
        "pirlo",
        "prefect",
        "autopass",
        "--task",
        "Search Google",
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

        mock_session_cli.assert_called_once()
        assert sys.argv[0] == "pirlo autopass"
        assert sys.argv[1] == "--task"
        assert sys.argv[2] == "Search Google"
        assert sys.argv[3] == "--help"
        assert sys.argv[4] == "--"
        assert sys.argv[5] == "prefect"
