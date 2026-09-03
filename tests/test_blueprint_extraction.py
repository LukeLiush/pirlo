# tests/test_blueprint_extraction.py
from __future__ import annotations

import asyncio

from pirlo.core.decorators import playbook
from pirlo.core.models.blueprint import (
    BlueprintNode,
    PlaybookBlueprint,
    PlaybookOutput,
)
from pirlo.core.ports.pitch import Pitch, PlayerNode, players


class LoginOutput(PlaybookOutput):
    auth_token: str
    user_id: str


class VerifyOutput(PlaybookOutput):
    verification_code: str


class CheckoutOutput(PlaybookOutput):
    order_id: str


class LoginTestPlaybook(Pitch[LoginOutput]):
    async def play(self, profile: str = "default") -> LoginOutput:
        return LoginOutput(auth_token="token_test_123", user_id="user_test_99")


class VerifyTestPlaybook(Pitch[VerifyOutput]):
    async def play(self, user_id: str = "") -> VerifyOutput:
        return VerifyOutput(verification_code="code_777")


class CheckoutTestPlaybook(Pitch[CheckoutOutput]):
    async def play(
        self, auth_token: str = "", verification_code: str = "", item_id: str = ""
    ) -> CheckoutOutput:
        return CheckoutOutput(order_id=f"order_{item_id}_{auth_token}")


@playbook(name="test_checkout_dag")
class CheckoutDAGPlaybook(Pitch[CheckoutOutput]):
    async def play(self, item_id: str = "item_42") -> CheckoutOutput:
        player_login: PlayerNode = self.player(LoginTestPlaybook, profile="prod")
        player_verify: PlayerNode = self.player(
            VerifyTestPlaybook, user_id=player_login.ball.user_id
        )
        player_checkout: PlayerNode = self.player(
            CheckoutTestPlaybook,
            auth_token=player_login.ball.auth_token,
            verification_code=player_verify.ball.verification_code,
            item_id=item_id,
        ).after(player_login, player_verify)

        return await self.kickoff([player_login, player_verify, player_checkout])


def test_extract_blueprint_and_ball_proxy():
    workflow = CheckoutDAGPlaybook()
    blueprint: PlaybookBlueprint = workflow.extract_blueprint()

    assert blueprint.name == "CheckoutDAGPlaybook"
    assert len(blueprint.nodes) == 3

    node1: BlueprintNode = blueprint.nodes[0]
    assert node1.playbook_name == "LoginTestPlaybook"
    assert node1.static_kwargs == {"profile": "prod"}

    node2: BlueprintNode = blueprint.nodes[1]
    assert node2.playbook_name == "VerifyTestPlaybook"
    assert "user_id" in node2.param_bindings
    assert node2.param_bindings["user_id"].source_node_id == node1.node_id
    assert node2.param_bindings["user_id"].source_field == "user_id"

    node3: BlueprintNode = blueprint.nodes[2]
    assert node3.playbook_name == "CheckoutTestPlaybook"
    assert node3.static_kwargs == {"item_id": "item_42"}
    assert "auth_token" in node3.param_bindings
    assert node3.param_bindings["auth_token"].source_node_id == node1.node_id
    assert node3.depends_on == [node1.node_id, node2.node_id]


def test_players_group_operator_syntax():
    class GroupDAGPlaybook(Pitch[CheckoutOutput]):
        async def play(self, item_id: str = "item_99") -> CheckoutOutput:
            p1 = self.player(LoginTestPlaybook, profile="dev")
            p2 = self.player(VerifyTestPlaybook, user_id=p1.ball.user_id)
            p3 = self.player(
                CheckoutTestPlaybook,
                auth_token=p1.ball.auth_token,
                verification_code=p2.ball.verification_code,
                item_id=item_id,
            )

            # Use players() helper with >> operator
            players(p1, p2) >> p3

            return await self.kickoff([p1, p2, p3])

    blueprint: PlaybookBlueprint = GroupDAGPlaybook().extract_blueprint()
    assert len(blueprint.nodes) == 3
    node3: BlueprintNode = blueprint.nodes[2]
    assert sorted(node3.depends_on) == sorted(
        [blueprint.nodes[0].node_id, blueprint.nodes[1].node_id]
    )


def test_practice_run_local_execution():
    workflow = CheckoutDAGPlaybook()
    result: CheckoutOutput = asyncio.run(workflow.play(item_id="item_777"))

    assert isinstance(result, CheckoutOutput)
    assert result.order_id == "order_item_777_token_test_123"
