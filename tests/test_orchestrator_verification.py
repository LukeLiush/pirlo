from __future__ import annotations

from unittest.mock import MagicMock, patch

from pirlo.core.models.orchestrator import OrchestratorVerificationResult
from pirlo.infrastructure.adapters.orchestrator.prefect.models import PrefectLink
from pirlo.infrastructure.adapters.orchestrator.prefect.plugin import PrefectPlugin


def test_prefect_verify_connection_ephemeral() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(name="local", server_url="ephemeral")

    res = plugin.verify(link)
    assert isinstance(res, OrchestratorVerificationResult)
    assert res.success is True
    assert "ephemeral" in res.message.lower()
    assert res.details.get("mode") == "ephemeral"


def test_prefect_verify_connection_server_healthy() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(
        name="prod",
        server_url="http://prefect.corp:4200/api",
        work_pool="k8s-pool",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        res = plugin.verify(link)
        mock_get.assert_called_once_with(
            "http://prefect.corp:4200/api/health", timeout=3.0
        )
        assert res.success is True
        assert "Connected to Prefect server" in res.message
        assert res.details.get("status_code") == 200
        assert res.details.get("work_pool") == "k8s-pool"


def test_prefect_verify_connection_server_unhealthy() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(
        name="prod",
        server_url="http://prefect.corp:4200/api",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch("httpx.get", return_value=mock_resp):
        res = plugin.verify(link)
        assert res.success is False
        assert "503" in res.message
        assert res.details.get("status_code") == 503


def test_prefect_verify_connection_server_network_error() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(
        name="prod",
        server_url="http://prefect.corp:4200/api",
    )

    with patch("httpx.get", side_effect=ConnectionError("Connection refused")):
        res = plugin.verify(link)
        assert res.success is False
        assert "Connection failed" in res.message
        assert "Connection refused" in res.details.get("error", "")


def test_prefect_verify_connection_server_auto_api_suffix() -> None:
    plugin = PrefectPlugin()
    link = PrefectLink(
        name="staging",
        server_url="http://prefect.corp:4200",  # Without /api
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        res = plugin.verify(link)
        mock_get.assert_called_once_with(
            "http://prefect.corp:4200/api/health", timeout=3.0
        )
        assert res.success is True
