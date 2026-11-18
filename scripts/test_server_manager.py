
"""Manual integration test for MCSync server management."""

import time
from pathlib import Path

from mcsync.config import MCSyncConfig
from mcsync.server import ServerManager


ROOT = Path(__file__).resolve().parents[1]

config = MCSyncConfig.from_file(
    ROOT / "config" / "local.json"
)

manager = ServerManager(config)

print("Starting Minecraft through MCSync...")

server = manager.start()

print(f"Process PID: {server.pid}")
print(f"Server log: {server.log_path}")

try:
    print("\nWaiting for Minecraft to finish starting...")

    ready = False
    deadline = time.monotonic() + 240

    while time.monotonic() < deadline:
        if not server.is_running:
            raise RuntimeError(
                "Minecraft exited during startup. "
                f"Check: {server.log_path}"
            )

        try:
            log = server.log_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            log = ""

        if "Done (" in log and ")! For help" in log:
            ready = True
            break

        time.sleep(2)

    if not ready:
        raise TimeoutError(
            "Minecraft did not report readiness within 240 seconds. "
            f"Check: {server.log_path}"
        )

    print("\nMINECRAFT READY!")
    print(f"Status: {manager.status()}")

    input(
        "\nJoin localhost:25566 in Minecraft. "
        "When finished, press Enter here to shut down the server..."
    )

    print("\nSending save-all flush...")
    manager.send_command("save-all flush")

    input(
        "Wait for the save confirmation in the server log, "
        "then press Enter to stop Minecraft..."
    )

finally:
    if server.is_running:
        print("\nRequesting graceful shutdown...")
        manager.stop(timeout=180)

    print("Minecraft process has exited.")
