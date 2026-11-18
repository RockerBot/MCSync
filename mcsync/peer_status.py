
"""Read-only status reporting for an MCSync peer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcsync.replication import get_latest_verified_replica


def build_peer_status(manager: Any) -> dict:
    """Build a read-only status report for this peer."""

    config = manager.config
    server_status = manager.status()

    registry = config.peer_registry
    protocol_version = (
        registry.protocol_version if registry is not None else 1
    )

    replica = get_latest_verified_replica(
        config.replication_directory,
        expected_world_id=config.world_id,
    )

    replica_status = None

    if replica is not None:
        metadata = replica["metadata"]

        replica_status = {
            "generation": replica["generation"],
            "manifest_sha256": metadata["manifest_sha256"],
            "created_at_utc": metadata["created_at_utc"],
            "created_by": metadata["created_by"],
            "clean_shutdown": metadata["clean_shutdown"],
            "file_count": metadata["file_count"],
        }

    server = {
        "state": server_status["state"],
        "pid": server_status.get("pid"),
    }

    if server_status.get("started_at") is not None:
        server["started_at"] = server_status["started_at"]

    if server_status.get("return_code") is not None:
        server["return_code"] = server_status["return_code"]

    return {
        "protocol_version": protocol_version,
        "peer_id": config.peer_id,
        "world_id": config.world_id,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "minecraft": {
            "version": config.minecraft_version,
            "loader": config.loader,
            "loader_version": config.loader_version,
        },
        "server": server,
        "ownership_lock_held": manager.ownership_lock.is_held,
        "latest_verified_replica": replica_status,
    }
