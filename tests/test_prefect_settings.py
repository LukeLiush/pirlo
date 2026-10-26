from pirlo.infrastructure.adapters.orchestrator.prefect_settings import (
    PrefectServerSettings,
)


def test_web_ui_base_keeps_hosts_containing_api():
    settings = PrefectServerSettings(api_url="http://api.internal:4200/api")

    assert settings.web_ui_base == "http://api.internal:4200"


def test_resolve_strips_trailing_slash_after_api():
    assert PrefectServerSettings.resolve("http://h:4200/api/").api_url == (
        "http://h:4200/api"
    )


def test_resolve_appends_api_when_missing():
    assert PrefectServerSettings.resolve("http://h:4200/").api_url == (
        "http://h:4200/api"
    )
