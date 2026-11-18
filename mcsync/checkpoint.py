
"""Safe stop-snapshot-restart checkpoint workflow."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from mcsync.server import ServerError, ServerManager
from mcsync.snapshots import create_snapshot, verify_snapshot
from mcsync.replication import publish_snapshot


class CheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be completed safely."""


@dataclass(frozen=True)
class CheckpointResult:
    snapshot_directory: Path
    generation: int
    restarted: bool
    replica_directory: Path | None = None
    replication_error: str | None = None


def _wait_for_save_confirmation(
    manager: ServerManager,
    log_path: Path,
    log_offset: int,
    timeout: float,
) -> None:
    """Wait for a save confirmation written after save-all was sent."""

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        server = manager.server

        if server is None or not server.is_running:
            raise CheckpointError(
                "Minecraft exited before confirming the save. "
                "No snapshot was created."
            )

        try:
            with log_path.open("rb") as log_file:
                log_file.seek(log_offset)
                new_text = log_file.read().decode(
                    "utf-8",
                    errors="replace",
                )
        except OSError as exc:
            raise CheckpointError(
                f"Could not read the Minecraft log: {exc}"
            ) from exc

        if "Saved the game" in new_text:
            return

        time.sleep(1)

    raise CheckpointError(
        f"Minecraft did not confirm the save within {timeout} seconds. "
        "The server has been left running; no snapshot was created."
    )


def create_checkpoint(
    manager: ServerManager,
    *,
    created_by: str,
    restart: bool = True,
    save_timeout: float = 120,
    stop_timeout: float = 180,
) -> CheckpointResult:
    """Stop Minecraft cleanly, snapshot its world, and optionally restart."""

    if not created_by.strip():
        raise ValueError("created_by cannot be empty")

    if save_timeout <= 0 or stop_timeout <= 0:
        raise ValueError("Timeouts must be greater than zero")

    server = manager.server

    if server is None or not server.is_running:
        raise CheckpointError(
            "MCSync does not currently own a running Minecraft server."
        )

    log_path = server.log_path

    try:
        log_offset = log_path.stat().st_size
    except OSError as exc:
        raise CheckpointError(
            f"Could not inspect the Minecraft log: {exc}"
        ) from exc

    print("Sending save-all flush...")
    manager.send_command("save-all flush")

    print("Waiting for Minecraft to confirm the save...")
    _wait_for_save_confirmation(
        manager,
        log_path,
        log_offset,
        save_timeout,
    )

    print("Save confirmed. Requesting graceful shutdown...")
    try:
        manager.stop(
            timeout=stop_timeout,
            release_ownership=False,
        )
    except ServerError as exc:
        raise CheckpointError(
            "Minecraft did not shut down cleanly. "
            "No snapshot was created and no second server was started. "
            f"Details: {exc}"
        ) from exc

    print("Minecraft has stopped. Creating snapshot...")

    try:
        snapshot_directory = create_snapshot(
            manager.config,
            created_by=created_by,
            clean_shutdown=True,
        )

        verification = verify_snapshot(
            snapshot_directory,
            expected_world_id=manager.config.world_id,
        )

        if not verification:
            raise CheckpointError(
                "The newly created snapshot did not pass verification."
            )

    except Exception as snapshot_error:
        if restart:
            print("Snapshot failed. Attempting to restart Minecraft...")
            try:
                manager.start()
            except Exception as restart_error:
                raise CheckpointError(
                    "Snapshot creation failed, and Minecraft could not "
                    f"be restarted: {restart_error}. "
                    "Ownership has been retained for safety."
                ) from snapshot_error
        else:
            manager.release_ownership()

        raise CheckpointError(
            f"Snapshot creation or verification failed: {snapshot_error}"
        ) from snapshot_error

    # Replication is secondary to the verified local snapshot.
    replica_directory = None
    replication_error = None

    print("Local snapshot verified. Publishing replica...")

    try:
        replica_directory = publish_snapshot(
            snapshot_directory,
            manager.config.replication_directory,
            expected_world_id=manager.config.world_id,
        )

        print(f"Replica published: {replica_directory}")

    except Exception as exc:
        replication_error = f"{type(exc).__name__}: {exc}"

        print(
            "WARNING: Local snapshot is safe, but replication failed: "
            f"{replication_error}"
        )

    generation = int(snapshot_directory.name.split("-")[-1])

    restarted = False

    if restart:
        print("Snapshot verified. Restarting Minecraft...")
        manager.start()
        restarted = True
    else:
        manager.release_ownership()

    return CheckpointResult(
        snapshot_directory=snapshot_directory,
        generation=generation,
        restarted=restarted,
        replica_directory=replica_directory,
        replication_error=replication_error,
    )
