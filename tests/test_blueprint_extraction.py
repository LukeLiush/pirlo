# tests/test_blueprint_extraction.py
from __future__ import annotations

import asyncio

from pirlo.core.decorators import play
from pirlo.core.models.blueprint import (
    PlayBlueprint,
    PlayOutput,
)
from pirlo.core.ports.play import Play, requires


class LoginOutput(PlayOutput):
    auth_token: str
    user_id: str


class VerifyOutput(PlayOutput):
    verification_code: str


class CheckoutOutput(PlayOutput):
    order_id: str


class LoginTestPlay(Play[LoginOutput]):
    async def execute(self, profile: str = "default") -> LoginOutput:
        return LoginOutput(auth_token="token_test_123", user_id="user_test_99")


class VerifyTestPlay(Play[VerifyOutput]):
    login: LoginOutput = requires(LoginTestPlay)

    async def execute(self) -> VerifyOutput:
        return VerifyOutput(verification_code="code_777")


@play(name="test_checkout_dag")
class CheckoutDAGPlay(Play[CheckoutOutput]):
    login: LoginOutput = requires(LoginTestPlay, profile="prod")
    verify: VerifyOutput = requires(VerifyTestPlay)

    async def execute(self, item_id: str = "item_42") -> CheckoutOutput:
        return CheckoutOutput(
            order_id=f"order_{item_id}_{self.login.auth_token}_{self.verify.verification_code}"
        )


def test_extract_blueprint():
    workflow = CheckoutDAGPlay()
    blueprint: PlayBlueprint = workflow.extract_blueprint()

    assert blueprint.name == "CheckoutDAGPlay"
    assert len(blueprint.nodes) == 3

    node_names = [n.playbook_name for n in blueprint.nodes]
    assert "LoginTestPlay" in node_names
    assert "VerifyTestPlay" in node_names
    assert "CheckoutDAGPlay" in node_names

    login_node = next(n for n in blueprint.nodes if n.playbook_name == "LoginTestPlay")
    verify_node = next(
        n for n in blueprint.nodes if n.playbook_name == "VerifyTestPlay"
    )
    checkout_node = next(
        n for n in blueprint.nodes if n.playbook_name == "CheckoutDAGPlay"
    )

    assert login_node.static_kwargs == {"profile": "prod"}
    assert login_node.node_id in verify_node.depends_on
    assert login_node.node_id in checkout_node.depends_on
    assert verify_node.node_id in checkout_node.depends_on


def test_practice_run_local_execution():
    workflow = CheckoutDAGPlay()
    result: CheckoutOutput = asyncio.run(workflow.run_play(item_id="item_777"))

    assert isinstance(result, CheckoutOutput)
    assert result.order_id == "order_item_777_token_test_123_code_777"
