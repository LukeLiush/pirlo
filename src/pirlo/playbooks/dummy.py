import asyncio
from typing import Annotated, Any

from pirlo.core.decorators import playbook
from pirlo.core.models.parameters import Parameter
from pirlo.core.models.run_result import RunResult
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


@playbook(name="dummy", description="Dummy test session for console verification.")
class DummySession(TerminalPitch):
    """Dummy test session for console verification."""

    async def play(
        self,
        target: Annotated[str, Parameter(help="Target host and port")] = "localhost:8080",
        retries: Annotated[int, Parameter(help="Number of retry attempts")] = 3,
        verbose: Annotated[bool, Parameter(help="Enable verbose logging")] = True,
        message: Annotated[str, Parameter(help="Message to print")] = "Initialization sequence started...",
        *args: Any,
        **kwargs: Any,
    ) -> RunResult[Any]:
        # 1. Header (Banner)
        self.header(
            "Dummy Session CLI",
            subtitle="Mock testing console integrations",
        )

        # 2. Print initial inputs
        print("[INFO] Starting dummy command...")
        print(f"[INFO] Target: {target}")
        print(f"[INFO] Retries set to: {retries}")
        print(f"[INFO] Verbose mode: {verbose}")

        await asyncio.sleep(0.5)

        # 3. Simulate processing steps
        for i in range(1, retries + 1):
            print(f"[INFO] Executing deployment steps (Attempt {i}/{retries})...")
            await asyncio.sleep(0.6)

            if verbose:
                print(f"[LOG] Processing details: {message}")
                await asyncio.sleep(0.4)

        print("[INFO] Verifying deployment... OK")
        await asyncio.sleep(0.5)

        # 4. Goal! (Success box)
        self.goal(
            "Dummy command completed successfully!",
            detail=f"Target {target} is fully initialized.",
        )
        return RunResult(
            run_id=(await self.prepared_run()).run_id if self._prepared_run else "dummy-run",
            data={"target": target, "retries": retries},
        )


if __name__ == "__main__":
    DummySession.cli()
