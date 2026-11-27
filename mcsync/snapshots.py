
"""Safe, immutable Minecraft world snapshots for MCSync."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from mcsync.config import MCSyncConfig


class SnapshotError(RuntimeError):
    """Raised when snapshot creation or verification fails."""


_GENERATION_PATTERN = re.compile(r"^generation-(\d+)$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest().upper()


def _json_bytes(data: Any) -> bytes:
    return (
        json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _safe_manifest_path(value: str) -> Path:
    """Convert old Windows or new portable paths into a safe local path."""

    normalized = value.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(value)

    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or not posix.parts
    ):
        raise SnapshotError(f"Unsafe manifest path: {value!r}")

    return Path(*posix.parts)


def _detect_java_version(config: MCSyncConfig) -> str:
    """Read the Java major version from the configured executable."""

    try:
        result = subprocess.run(
            [str(config.java_executable), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"

    output = result.stdout + result.stderr
    match = re.search(r'version "(?:1\.)?(\d+)', output)

    return match.group(1) if match else "unknown"


def _build_manifest(world_copy: Path) -> list[dict[str, Any]]:
    """Build a sorted manifest of every regular file in a world copy."""

    entries = []

    for path in sorted(world_copy.rglob("*")):
        if path.is_symlink():
            raise SnapshotError(
                f"World contains a symbolic link: {path}"
            )

        if not path.is_file():
            continue

        entries.append({
            "path": path.relative_to(world_copy).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        })

    if not entries:
        raise SnapshotError("World directory contains no files")

    return entries


def verify_snapshot(
    snapshot_directory: Path,
    expected_world_id: str | None = None,
) -> dict[str, Any]:
    """Verify metadata, manifest hash, file count, sizes and file hashes.

    Raises SnapshotError if any check fails. Returns metadata on success.
    """

    snapshot_directory = Path(snapshot_directory)

    metadata_path = snapshot_directory / "metadata.json"
    manifest_path = snapshot_directory / "manifest.json"

    if not metadata_path.is_file() or not manifest_path.is_file():
        raise SnapshotError("Snapshot is missing metadata.json or manifest.json")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"Cannot read snapshot metadata or manifest: {exc}") from exc

    if not isinstance(metadata, dict) or not isinstance(manifest, list):
        raise SnapshotError("Invalid metadata or manifest structure")

    required_metadata = (
        "world_id",
        "generation",
        "clean_shutdown",
        "file_count",
        "manifest_sha256",
    )

    missing = [key for key in required_metadata if key not in metadata]
    if missing:
        raise SnapshotError(
            f"Metadata is missing fields: {', '.join(missing)}"
        )

    if expected_world_id and metadata["world_id"] != expected_world_id:
        raise SnapshotError("Snapshot belongs to a different world")

    if metadata["clean_shutdown"] is not True:
        raise SnapshotError("Snapshot is not marked as a clean shutdown")

    actual_manifest_hash = hashlib.sha256(manifest_bytes).hexdigest().upper()

    if actual_manifest_hash != str(metadata["manifest_sha256"]).upper():
        raise SnapshotError("Manifest SHA-256 does not match metadata")

    if metadata["file_count"] != len(manifest):
        raise SnapshotError("Manifest file count does not match metadata")

    world_id = metadata["world_id"]
    if not isinstance(world_id, str) or not world_id.strip():
        raise SnapshotError("Invalid world_id in metadata")

    world_copy = snapshot_directory / "world" / world_id
    if not world_copy.is_dir():
        raise SnapshotError(f"Snapshot world directory is missing: {world_copy}")

    for candidate in world_copy.rglob("*"):
        if candidate.is_symlink():
            raise SnapshotError(
                f"Snapshot contains a symbolic link: {candidate}"
            )

    seen_paths = set()

    for entry in manifest:
        if not isinstance(entry, dict):
            raise SnapshotError("Invalid manifest entry")

        try:
            relative_path = _safe_manifest_path(entry["path"])
            expected_size = entry["size"]
            expected_hash = entry["sha256"]
        except (KeyError, TypeError) as exc:
            raise SnapshotError(f"Invalid manifest entry: {entry}") from exc

        key = relative_path.as_posix().casefold()
        if key in seen_paths:
            raise SnapshotError(f"Duplicate manifest path: {entry['path']}")
        seen_paths.add(key)

        file_path = world_copy / relative_path

        if file_path.is_symlink() or not file_path.is_file():
            raise SnapshotError(f"Snapshot file is missing: {entry['path']}")

        if file_path.stat().st_size != expected_size:
            raise SnapshotError(f"File size mismatch: {entry['path']}")

        if _sha256_file(file_path) != str(expected_hash).upper():
            raise SnapshotError(f"SHA-256 mismatch: {entry['path']}")

    actual_paths = {
        path.relative_to(world_copy).as_posix().casefold()
        for path in world_copy.rglob("*")
        if path.is_file()
    }

    if actual_paths != seen_paths:
        raise SnapshotError(
            "Snapshot contains missing or unlisted files"
        )

    return metadata


def _existing_generations(snapshots_directory: Path) -> list[tuple[int, Path]]:
    """Find and verify all published generations; fail closed on corruption."""

    generations = []

    for path in snapshots_directory.iterdir():
        if not path.is_dir():
            continue

        match = _GENERATION_PATTERN.fullmatch(path.name)
        if not match:
            continue

        number = int(match.group(1))

        try:
            metadata = verify_snapshot(path)
        except SnapshotError as exc:
            raise SnapshotError(
                f"Existing generation {path.name} failed verification: {exc}. "
                "Refusing to create another generation."
            ) from exc

        if metadata["generation"] != number:
            raise SnapshotError(
                f"Generation number mismatch in {path.name}"
            )

        generations.append((number, path))

    return sorted(generations)

def _copytree_ignore(source, config):
    def inner(path, names):
        path = Path(path)
        # print(f'SNAPSHOT_EXCLUSION {path == source}: {source!r} against {path!r}')
        return config.snapshot_exclusion_files * (path == source)  # TODO: Allow files at any depth.
    return inner

def create_snapshot(
    config: MCSyncConfig,
    *,
    created_by: str,
    clean_shutdown: bool = False,
) -> Path:
    """Create and verify a new snapshot from a cleanly stopped server."""

    if clean_shutdown is not True:
        raise SnapshotError(
            "Refusing to snapshot: confirm the Minecraft server "
            "has completely shut down."
        )

    if not created_by or not created_by.strip():
        raise SnapshotError("created_by cannot be empty")

    print('Validating config...')
    config.validate()

    source = config.world_directory.resolve()
    snapshots_directory = config.snapshots_directory.resolve()

    if not source.is_dir():
        raise SnapshotError(f"World directory does not exist: {source}")

    print('Found source dir:', source)

    if (
        snapshots_directory == source
        or snapshots_directory.is_relative_to(source)
        or source.is_relative_to(snapshots_directory)
    ):
        raise SnapshotError(
            "World and snapshots directories must not contain one another"
        )

    for path in source.rglob("*"):
        if path.is_symlink():
            raise SnapshotError(
                f"World contains a symbolic link: {path}"
            )

    print('Not a symlink. All verified. Creating directory:', snapshots_directory)

    snapshots_directory.mkdir(parents=True, exist_ok=True)

    existing = _existing_generations(snapshots_directory)

    if existing:
        parent_generation = existing[-1][0]
        next_generation = parent_generation + 1
    else:
        parent_generation = None
        next_generation = 1

    generation_name = f"generation-{next_generation:06d}"
    final_directory = snapshots_directory / generation_name

    if final_directory.exists():
        raise SnapshotError(
            f"Refusing to overwrite existing snapshot: {final_directory}"
        )

    print('Will write to:', final_directory)

    staging_directory = snapshots_directory / (
        f".staging-{generation_name}-{uuid.uuid4().hex}"
    )
    print('Staging dir:', staging_directory)

    try:
        world_copy = staging_directory / "world" / config.world_id
        world_copy.parent.mkdir(parents=True)

        print(f'Copying {source!r} into {world_copy!r}')
        shutil.copytree(
            source, world_copy,
            ignore=_copytree_ignore(source, config)
        )

        manifest = _build_manifest(world_copy)
        manifest_bytes = _json_bytes(manifest)

        manifest_path = staging_directory / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)

        metadata = {
            "world_id": config.world_id,
            "generation": next_generation,
            "parent_generation": parent_generation,
            "created_by": created_by,
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "minecraft_version": config.minecraft_version,
            "loader": config.loader,
            "loader_version": config.loader_version,
            "java_version": _detect_java_version(config),
            "clean_shutdown": True,
            "file_count": len(manifest),
            "manifest_sha256": hashlib.sha256(
                manifest_bytes
            ).hexdigest().upper(),
        }

        (staging_directory / "metadata.json").write_bytes(
            _json_bytes(metadata)
        )

        verify_snapshot(staging_directory, config.world_id)
        print('Verified snapshot. Promoting staged snapshot...')

        print('Metadata:', json.dumps(metadata, indent=2))

        # Same-filesystem rename: publish only after verification succeeds.
        staging_directory.rename(final_directory)
        print(f'Renamed {staging_directory!r} to {final_directory!r}')


        return final_directory

    except Exception:
        if staging_directory.exists():
            shutil.rmtree(staging_directory, ignore_errors=True)
        raise


def list_snapshots(
    snapshots_directory: Path,
    expected_world_id: str | None = None,
) -> list[dict[str, Any]]:
    """List verified snapshot generations, oldest first."""

    snapshots_directory = Path(snapshots_directory)

    if not snapshots_directory.is_dir():
        return []

    results = []

    for path in snapshots_directory.iterdir():
        if not path.is_dir():
            continue

        match = _GENERATION_PATTERN.fullmatch(path.name)
        if not match:
            continue

        metadata = verify_snapshot(path, expected_world_id)

        generation = int(match.group(1))
        if metadata["generation"] != generation:
            raise SnapshotError(
                f"Generation number mismatch in {path.name}"
            )

        results.append({
            "generation": generation,
            "path": path,
            "metadata": metadata,
        })

    return sorted(results, key=lambda item: item["generation"])


def get_latest_snapshot(
    snapshots_directory: Path,
    expected_world_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the newest verified generation, or None."""

    snapshots = list_snapshots(
        snapshots_directory,
        expected_world_id,
    )

    return snapshots[-1] if snapshots else None


def get_retention_report(
    snapshots_directory: Path,
    keep: int = 2,
    expected_world_id: str | None = None,
) -> dict[str, Any]:
    """Report which generations would be retained or eligible for pruning.

    This function never deletes files.
    """

    if keep < 2:
        raise ValueError(
            "At least two generations must be retained"
        )

    snapshots = list_snapshots(
        snapshots_directory,
        expected_world_id,
    )

    retained = snapshots[-keep:]
    candidates = snapshots[:-keep]

    return {
        "total_generations": len(snapshots),
        "keep": keep,
        "retained": [
            item["generation"] for item in retained
        ],
        "prune_candidates": [
            item["generation"] for item in candidates
        ],
        "deletion_performed": False,
    }
