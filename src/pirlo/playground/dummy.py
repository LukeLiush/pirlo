import asyncio

from pirlo.core.ports.pitch import Parameter
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class DummySession(TerminalPitch):
    """Dummy test session for console verification."""

    target = Parameter(str, default="localhost:8080", help="Target host and port")
    retries = Parameter(int, default=3, help="Number of retry attempts")
    verbose = Parameter(bool, default=True, help="Enable verbose logging")
    message = Parameter(
        str, default="Initialization sequence started...", help="Message to print"
    )

    async def play(self):
        # 1. Header (Banner)
        self.header(
            "Dummy Session CLI",
            subtitle="Mock testing console integrations",
        )

        # 2. Print initial inputs
        print("[INFO] Starting dummy command...")
        print(f"[INFO] Target: {self.target}")
        print(f"[INFO] Retries set to: {self.retries}")
        print(f"[INFO] Verbose mode: {self.verbose}")

        await asyncio.sleep(0.5)

        # 3. Simulate processing steps
        for i in range(1, self.retries + 1):
            print(f"[INFO] Executing deployment steps (Attempt {i}/{self.retries})...")
            await asyncio.sleep(0.6)

            if self.verbose:
                print(f"[LOG] Processing details: {self.message}")
                await asyncio.sleep(0.4)

        print("[INFO] Verifying deployment... OK")
        await asyncio.sleep(0.5)

        # 4. Goal! (Success box)
        self.goal(
            "Dummy command completed successfully!",
            detail=f"Target {self.target} is fully initialized.",
        )


if __name__ == "__main__":
    DummySession.cli()
