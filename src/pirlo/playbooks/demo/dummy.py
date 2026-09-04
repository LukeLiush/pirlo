import asyncio
from typing import Annotated, Any

from pirlo.core.decorators import playbook
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run_result import RunResult
from pirlo.core.ports.playbook import Playbook


@playbook(name="demo_dummy", description="Dummy test session for console verification.")
class DummySession(Playbook):
    """Dummy test session for console verification."""

    async def play(
        self,
        target: Annotated[
            str, Parameter(help="Target host and port")
        ] = "localhost:8080",
        retries: Annotated[int, Parameter(help="Number of retry attempts")] = 3,
        verbose: Annotated[bool, Parameter(help="Enable verbose logging")] = True,
        message: Annotated[
            str, Parameter(help="Message to print")
        ] = "Initialization sequence started...",
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[Any]:
        # 1. Header (Banner)
        self.ui.header(
            "Dummy Session CLI",
            subtitle="Mock testing console integrations",
        )

        # 2. Print initial inputs
        self.ui.commentary("[INFO] Starting dummy command...")
        self.ui.commentary(f"[INFO] Target: {target}")
        self.ui.commentary(f"[INFO] Retries set to: {retries}")
        self.ui.commentary(f"[INFO] Verbose mode: {verbose}")
        with self.ui.status("Initializing deployment..."):
            await asyncio.sleep(1)
            # 3. Simulate processing steps
            for i in range(1, retries + 1):
                self.ui.commentary(
                    f"[INFO] Executing deployment steps (Attempt {i}/{retries})..."
                )
                await asyncio.sleep(0.6)

                if verbose:
                    self.ui.commentary(f"[LOG] Processing details: {message}")
                    await asyncio.sleep(0.4)

        self.ui.commentary("[INFO] Verifying deployment... OK")
        await asyncio.sleep(0.5)

        # 4. Goal! (Success box)
        self.ui.goal(
            "Dummy command completed successfully!",
            detail=f"Target {target} is fully initialized.",
        )
        return RunResult(
            run_id=(await self.prepared_run()).run_id
            if self._prepared_run
            else "dummy-run",
            data={"target": target, "retries": retries},
        )


if __name__ == "__main__":
    DummySession.cli()
