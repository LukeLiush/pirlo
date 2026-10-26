from pathlib import Path

import yaml

COMPOSE_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "pirlo"
    / "playbooks"
    / "serve"
    / "docker-compose.yml"
)


def test_serve_stack_publishes_ports_on_loopback_only():
    services = yaml.safe_load(COMPOSE_FILE.read_text())["services"]
    published = [
        (name, str(mapping))
        for name, service in services.items()
        for mapping in service.get("ports", [])
    ]

    assert published, "expected the serve stack to publish at least one port"
    for name, mapping in published:
        assert mapping.startswith("127.0.0.1:"), f"{name} publishes {mapping!r}"
