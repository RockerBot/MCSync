
"""Verified publication and discovery of MCSync snapshot replicas."""

from __future__ import annotations

import re
import shutil
import uuid

from pathlib import Path
from typing import Any

from mcsync.snapshots import SnapshotError, verify_snapshot


_GENERATION_PATTERN = re.compile(r"^generation-(\d+)$")


def _generation_number(directory: Path) -> int:
    """Get the generation number from a valid generation directory name."""

    match = _GENERATION_PATTERN.fullmatch(directory.name)

    if not match:
        raise SnapshotError(
            f"Invalid generation directory name: {directory.name}"
        )

    return int(match.group(1))


def _reject_symlinks(directory: Path) -> None:
    """Reject symbolic links anywhere inside a snapshot directory."""

    if directory.is_symlink():
        raise SnapshotError(
            f"Snapshot directory cannot be a symbolic link: {directory}"
        )

    for path in directory.rglob("*"):
        if path.is_symlink():
            raise SnapshotError(
                f"Snapshot contains a symbolic link: {path}"
            )


def verify_replica(
    replica_directory: Path,
    expected_world_id: str | None = None,
) -> dict[str, Any]:
    """Verify a received replica completely before treating it as usable."""

    replica_directory = Path(replica_directory)

    if not replica_directory.is_dir():
        raise SnapshotError(
            f"Replica directory does not exist: {replica_directory}"
        )

    generation = _generation_number(replica_directory)

    _reject_symlinks(replica_directory)

    metadata = verify_snapshot(
        replica_directory,
        expected_world_id,
    )

    if metadata["generation"] != generation:
        raise SnapshotError(
            f"Generation number mismatch in {replica_directory.name}"
        )

    return metadata


def publish_snapshot(
    snapshot_directory: Path,
    replication_directory: Path,
    expected_world_id: str | None = None,
) -> Path:
    """Verify and atomically publish a snapshot into the replication folder.

    Existing identical generations are accepted without being overwritten.
    An existing incomplete, corrupt, or different generation is never replaced.
    """

    snapshot_directory = Path(snapshot_directory)
    replication_directory = Path(replication_directory)

    if snapshot_directory.is_symlink():
        raise SnapshotError("Snapshot directory cannot be a symbolic link")

    if replication_directory.is_symlink():
        raise SnapshotError("Replication directory cannot be a symbolic link")

    snapshot_directory = snapshot_directory.resolve()
    replication_directory = replication_directory.resolve()

    if not snapshot_directory.is_dir():
        raise SnapshotError(
            f"Snapshot directory does not exist: {snapshot_directory}"
        )

    if (
        snapshot_directory == replication_directory
        or snapshot_directory.is_relative_to(replication_directory)
        or replication_directory.is_relative_to(snapshot_directory)
    ):
        raise SnapshotError(
            "Snapshot and replication directories must not contain one another"
        )

    generation = _generation_number(snapshot_directory)

    _reject_symlinks(snapshot_directory)

    source_metadata = verify_snapshot(
        snapshot_directory,
        expected_world_id,
    )

    if source_metadata["generation"] != generation:
        raise SnapshotError(
            f"Generation number mismatch in {snapshot_directory.name}"
        )

    replication_directory.mkdir(parents=True, exist_ok=True)

    if replication_directory.is_symlink():
        raise SnapshotError(
            "Replication directory cannot be a symbolic link"
        )

    final_directory = replication_directory / snapshot_directory.name

    if final_directory.exists():
        existing_metadata = verify_replica(
            final_directory,
            source_metadata["world_id"],
        )

        if (
            existing_metadata["generation"] == generation
            and existing_metadata["manifest_sha256"]
            == source_metadata["manifest_sha256"]
        ):
            return final_directory

        raise SnapshotError(
            f"Refusing to overwrite existing replica: {final_directory}"
        )

    staging_directory = replication_directory / (
        f".staging-{snapshot_directory.name}-{uuid.uuid4().hex}"
    )

    try:
        shutil.copytree(snapshot_directory, staging_directory)

        _reject_symlinks(staging_directory)

        staged_metadata = verify_snapshot(
            staging_directory,
            source_metadata["world_id"],
        )

        if (
            staged_metadata["generation"] != generation
            or staged_metadata["manifest_sha256"] != source_metadata["manifest_sha256"]
        ):
            raise SnapshotError(
                "Published copy does not match the source snapshot"
            )

        # Staging and final directories share a filesystem.
        # The final generation name appears only after verification.
        staging_directory.rename(final_directory)

        return final_directory

    except Exception:
        if staging_directory.exists():
            shutil.rmtree(staging_directory, ignore_errors=True)

        raise


def list_verified_replicas(
    replication_directory: Path,
    expected_world_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return complete, verified replicas, oldest first.

    Incomplete or corrupt directories are ignored. This is expected while
    Syncthing is still transferring files.
    """

    replication_directory = Path(replication_directory)

    if (
        not replication_directory.is_dir()
        or replication_directory.is_symlink()
    ):
        return []

    results = []

    for path in replication_directory.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue

        if not _GENERATION_PATTERN.fullmatch(path.name):
            continue

        try:
            metadata = verify_replica(
                path,
                expected_world_id,
            )
        except (SnapshotError, OSError, ValueError, TypeError, KeyError):
            # A transfer may be incomplete, or this generation may be corrupt.
            continue

        results.append({
            "generation": metadata["generation"],
            "path": path,
            "metadata": metadata,
        })

    return sorted(
        results,
        key=lambda item: item["generation"],
    )


def get_latest_verified_replica(
    replication_directory: Path,
    expected_world_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the newest fully verified replica, or None."""

    replicas = list_verified_replicas(
        replication_directory,
        expected_world_id,
    )

    return replicas[-1] if replicas else None

def import_incoming_snapshots(
    incoming_directory: Path,
    replication_directory: Path,
    expected_world_id: str | None = None,
) -> list[dict[str, Any]]:
    """Import verified snapshots from an untrusted incoming directory.

    Incoming files are never modified or deleted. Each valid generation is
    independently verified and published through publish_snapshot().
    Incomplete, corrupt, or conflicting generations are reported as rejected.
    """

    incoming_directory = Path(incoming_directory)
    replication_directory = Path(replication_directory)

    if incoming_directory.is_symlink():
        raise SnapshotError(
            "Incoming directory cannot be a symbolic link"
        )

    if replication_directory.is_symlink():
        raise SnapshotError(
            "Replication directory cannot be a symbolic link"
        )

    # A missing incoming directory is normal before the first transfer.
    if not incoming_directory.exists():
        return []

    if not incoming_directory.is_dir():
        raise SnapshotError(
            f"Incoming path is not a directory: {incoming_directory}"
        )

    incoming_directory = incoming_directory.resolve()
    replication_directory = replication_directory.resolve()

    if (
        incoming_directory == replication_directory
        or incoming_directory.is_relative_to(replication_directory)
        or replication_directory.is_relative_to(incoming_directory)
    ):
        raise SnapshotError(
            "Incoming and replication directories must not contain one another"
        )

    results = []

    for incoming_snapshot in sorted(incoming_directory.iterdir()):
        if not incoming_snapshot.is_dir():
            continue

        if incoming_snapshot.is_symlink():
            continue

        match = _GENERATION_PATTERN.fullmatch(incoming_snapshot.name)

        # Ignore staging folders and unrelated files/directories.
        if not match:
            continue

        result = {
            "generation": incoming_snapshot.name,
            "status": "REJECTED",
            "path": None,
            "error": None,
        }

        try:
            # Verify the incoming copy before attempting publication.
            incoming_metadata = verify_replica(
                incoming_snapshot,
                expected_world_id,
            )

            destination = (
                replication_directory / incoming_snapshot.name
            )

            if destination.exists():
                existing_metadata = verify_replica(
                    destination,
                    incoming_metadata["world_id"],
                )

                if (
                    existing_metadata["manifest_sha256"]
                    == incoming_metadata["manifest_sha256"]
                ):
                    result["status"] = "ALREADY_PRESENT"
                    result["path"] = destination
                    results.append(result)
                    continue

            published = publish_snapshot(
                incoming_snapshot,
                replication_directory,
                expected_world_id,
            )

            result["status"] = "IMPORTED"
            result["path"] = published

        except (
            SnapshotError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            result["error"] = str(exc)

        results.append(result)

    return results
