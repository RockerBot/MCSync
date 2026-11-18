
"""Manual integration test for a real MCSync checkpoint."""

import socket
import time
from pathlib import Path

from mcsync.checkpoint import create_checkpoint
from mcsync.config import MCSyncConfig
from mcsync.server import ServerManager


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "local.json"


def wait_until_ready(server, timeout=240):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not server.is_running:
            raise RuntimeError(
                f"Minecraft exited unexpectedly. Check {server.log_path}"
            )

        try:
            log = server.log_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            log = ""

        if "Done (" in log and ")! For help" in log:
            return

        time.sleep(2)

    raise TimeoutError(
        f"Minecraft did not become ready. Check {server.log_path}"
    )


def main():
    config = MCSyncConfig.from_file(CONFIG_PATH)
    manager = ServerManager(config)

    # Refuse to start if another server is already listening.
    sock = socket.socket()
    try:
        result = sock.connect_ex(("127.0.0.1", 25566))
    finally:
        sock.close()

    if result == 0:
        raise RuntimeError(
            "Port 25566 is already accepting connections. "
            "Stop the other server before continuing."
        )

    try:
        print("Starting Minecraft through MCSync...")
        server = manager.start()

        print(f"Process PID: {server.pid}")
        print(f"Log: {server.log_path}")

        print("Waiting for Minecraft startup...")
        wait_until_ready(server)

        print("\nMinecraft is ready at localhost:25566.")

        input(
            "Join the server and inspect the world. "
            "When ready, press Enter here to create a checkpoint..."
        )

        result = create_checkpoint(
            manager,
            created_by=config.peer_id,
            restart=True,
            save_timeout=120,
            stop_timeout=180,
        )

        print("\nCHECKPOINT SUCCESSFUL")
        print(f"Generation: {result.generation}")
        print(f"Snapshot: {result.snapshot_directory}")
        print(f"Restarted: {result.restarted}")

        print("\nWaiting for the restarted server...")
        wait_until_ready(manager.server)

        print("\nMinecraft restarted successfully.")
        input(
            "Reconnect to localhost:25566 and verify the world. "
            "When finished, press Enter here to stop the server..."
        )

    finally:
        if manager.server is not None and manager.server.is_running:
            print("\nRequesting graceful shutdown...")
            manager.stop(timeout=180)

        print("Integration test finished.")


if __name__ == "__main__":
    main()
