
"""Safe restoration of Minecraft worlds from verified replicas."""

from __future__ import annotations

import shutil
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcsync.replication import (
    get_latest_verified_replica,
    verify_replica,
)
from mcsync.snapshots import SnapshotError, verify_snapshot


class RecoveryError(RuntimeError):
    """Raised when world recovery cannot be completed safely."""


@dataclass(frozen=True)
class RecoveryResult:
    replica_directory: Path
    generation: int
    world_directory: Path
    backup_directory: Path | None


def _reject_symlinks(directory: Path) -> None:
    """Reject symbolic links anywhere in a recovery staging directory."""

    if directory.is_symlink():
        raise RecoveryError(
            f"Recovery directory cannot be a symbolic link: {directory}"
        )

    for path in directory.rglob("*"):
        if path.is_symlink():
            raise RecoveryError(
                f"Recovery data contains a symbolic link: {path}"
            )


def recover_world(
    manager,
    replica_directory: Path | None = None,
) -> RecoveryResult:
    """Restore a verified replica without starting Minecraft.

    The previous active world is preserved as a backup.
    Ownership remains held after successful recovery so the same
    ServerManager can safely start Minecraft.
    """

    config = manager.config

    if manager.server is not None and manager.server.is_running:
        raise RecoveryError(
            "Cannot recover while this manager's Minecraft server is running."
        )

    config.validate()

    world_directory = config.world_directory
    world_parent = world_directory.parent

    if world_directory.is_symlink():
        raise RecoveryError(
            "The active world directory cannot be a symbolic link."
        )

    if world_directory.exists() and not world_directory.is_dir():
        raise RecoveryError(
            f"The active world path is not a directory: {world_directory}"
        )

    acquired_here = False
    staging_directory = None
    backup_directory = None
    backup_created = False

    try:
        if not manager.ownership_lock.is_held:
            manager.ownership_lock.acquire()
            acquired_here = True

        # Select or verify the requested replica.
        if replica_directory is None:
            latest = get_latest_verified_replica(
                config.replication_directory,
                expected_world_id=config.world_id,
            )

            if latest is None:
                raise RecoveryError(
                    "No verified replica is available for this world."
                )

            replica_directory = latest["path"]

        replica_directory = Path(replica_directory)

        metadata = verify_replica(
            replica_directory,
            expected_world_id=config.world_id,
        )

        generation = metadata["generation"]

        # Stage beside the active world so installation uses the same
        # filesystem and directory renames can be atomic.
        world_parent.mkdir(parents=True, exist_ok=True)

        staging_directory = world_parent / (
            f".mcsync-recovery-{uuid.uuid4().hex}"
        )

        print(f"Copying replica generation {generation}...")

        shutil.copytree(
            replica_directory,
            staging_directory,
            symlinks=True,
        )

        _reject_symlinks(staging_directory)

        # Verify the copied data, not merely the original replica.
        staged_metadata = verify_snapshot(
            staging_directory,
            expected_world_id=config.world_id,
        )

        if (
            staged_metadata["generation"] != generation
            or staged_metadata["manifest_sha256"]
            != metadata["manifest_sha256"]
        ):
            raise RecoveryError(
                "Staged recovery copy does not match the verified replica."
            )

        staged_world = (
            staging_directory / "world" / config.world_id
        )

        if not staged_world.is_dir():
            raise RecoveryError(
                f"Staged world directory is missing: {staged_world}"
            )

        # Preserve the existing world before installing the new one.
        if world_directory.exists():
            timestamp = datetime.now(timezone.utc).strftime(
                "%Y%m%d-%H%M%S"
            )

            backup_directory = world_parent / (
                f"{world_directory.name}.backup-{timestamp}-"
                f"{uuid.uuid4().hex[:8]}"
            )

            print(f"Preserving existing world: {backup_directory}")

            world_directory.rename(backup_directory)
            backup_created = True

        try:
            staged_world.rename(world_directory)

        except Exception as install_error:
            if backup_created:
                try:
                    backup_directory.rename(world_directory)
                    backup_created = False

                except Exception as rollback_error:
                    # Keep ownership: the world is not in its original
                    # location, and another manager must not start it.
                    manager._retain_ownership = True

                    raise RecoveryError(
                        "World installation failed and rollback also failed. "
                        f"Previous world remains at: {backup_directory}. "
                        f"Installation error: {install_error}. "
                        f"Rollback error: {rollback_error}"
                    ) from rollback_error

            raise RecoveryError(
                f"Could not install recovered world: {install_error}"
            ) from install_error

        # Recovery succeeded. Retain ownership until start() or an
        # explicit release_ownership() call.
        manager._retain_ownership = True

        print("World recovery completed successfully.")

        return RecoveryResult(
            replica_directory=replica_directory,
            generation=generation,
            world_directory=world_directory,
            backup_directory=backup_directory,
        )

    except Exception as exc:
        if acquired_here and not manager._retain_ownership:
            manager.ownership_lock.release()

        if isinstance(exc, RecoveryError):
            raise

        raise RecoveryError(
            f"World recovery failed: {exc}"
        ) from exc

    finally:
        if (
            staging_directory is not None
            and staging_directory.exists()
        ):
            shutil.rmtree(staging_directory, ignore_errors=True)
