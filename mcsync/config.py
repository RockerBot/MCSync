
"""Configuration loading and validation for MCSync."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from mcsync.peers import PeerRegistry


@dataclass(frozen=True)
class MCSyncConfig:
    """Configuration for one MCSync peer."""

    peer_id: str
    world_id: str

    server_directory: Path
    world_directory: Path
    snapshots_directory: Path
    replication_directory: Path
    runtime_directory: Path

    java_executable: Path
    server_start_command: tuple[str, ...]

    minecraft_version: str
    loader: str
    loader_version: str

    checkpoint_interval_minutes: int = 10
    peer_registry: PeerRegistry | None = None
    secrets_file: Path | None = None

    @classmethod
    def from_file(cls, config_path: Path) -> "MCSyncConfig":
        """Load configuration from a JSON file."""

        config_path = config_path.expanduser().resolve()

        if not config_path.is_file():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}"
            )

        with config_path.open("r", encoding="utf-8") as file:
            data: dict[str, Any] = json.load(file)

        required = (
            "peer_id",
            "world_id",
            "server_directory",
            "world_directory",
            "snapshots_directory",
            "java_executable",
            "server_start_command",
            "minecraft_version",
            "loader",
            "loader_version",
        )

        missing = [
            key for key in required
            if key not in data
        ]

        if missing:
            raise ValueError(
                f"Missing configuration fields: {', '.join(missing)}"
            )

        base_directory = config_path.parent

        def resolve_path(value: str) -> Path:
            path = Path(value).expanduser()

            if not path.is_absolute():
                path = base_directory / path

            return path.resolve()
        
        runtime_directory = (
            resolve_path(data["runtime_directory"])
            if data.get("runtime_directory")
            else resolve_path(data["server_directory"]) / ".mcsync"
        )

        replication_directory = (
            resolve_path(data["replication_directory"])
            if data.get("replication_directory")
            else (base_directory.parent / "MCSyncData" / "replication").resolve()
        )

        secrets_file = (
            resolve_path(data["secrets_file"])
            if data.get("secrets_file")
            else (base_directory / "secrets.json").resolve()
        )

        command = data["server_start_command"]

        if not isinstance(command, list) or not command:
            raise ValueError(
                "server_start_command must be a non-empty JSON array"
            )

        if not all(isinstance(part, str) and part for part in command):
            raise ValueError(
                "Every server_start_command entry must be a non-empty string"
            )

        interval = data.get("checkpoint_interval_minutes", 10)

        if not isinstance(interval, int) or isinstance(interval, bool):
            raise ValueError(
                "checkpoint_interval_minutes must be an integer"
            )

        if interval < 1:
            raise ValueError(
                "checkpoint_interval_minutes must be at least 1"
            )

        registry_path = base_directory / "peers.json"

        peer_registry = (
            PeerRegistry.from_file(registry_path)
            if registry_path.is_file()
            else None
        )

        return cls(
            peer_id=str(data["peer_id"]),
            world_id=str(data["world_id"]),
            server_directory=resolve_path(data["server_directory"]),
            world_directory=resolve_path(data["world_directory"]),
            snapshots_directory=resolve_path(data["snapshots_directory"]),
            replication_directory=replication_directory,
            runtime_directory=runtime_directory,
            java_executable=resolve_path(data["java_executable"]),
            server_start_command=tuple(command),
            minecraft_version=str(data["minecraft_version"]),
            loader=str(data["loader"]),
            loader_version=str(data["loader_version"]),
            checkpoint_interval_minutes=interval,
            peer_registry=peer_registry,
            secrets_file=secrets_file,
        )

    def validate(self) -> None:
        """Validate local paths and configuration."""

        if not self.server_directory.is_dir():
            raise ValueError(
                f"Server directory does not exist: {self.server_directory}"
            )

        if not self.world_directory.is_dir():
            raise ValueError(
                f"World directory does not exist: {self.world_directory}"
            )

        if not self.java_executable.is_file():
            raise ValueError(
                f"Java executable not found: {self.java_executable}"
            )

        if not self.snapshots_directory.is_absolute():
            raise ValueError("Snapshots directory must be absolute")

        if self.world_directory == self.snapshots_directory:
            raise ValueError(
                "World and snapshots directories must be different"
            )

        if not self.peer_id.strip() or not self.world_id.strip():
            raise ValueError("peer_id and world_id cannot be empty")

        if (
            self.runtime_directory == self.world_directory
            or self.world_directory in self.runtime_directory.parents
        ):
            raise ValueError(
                "Runtime directory cannot be inside the Minecraft world directory"
            )
        
        if not self.replication_directory.is_absolute():
            raise ValueError("Replication directory must be absolute")

        if self.secrets_file is not None and not self.secrets_file.is_absolute():
            raise ValueError("Secrets file path must be absolute")

        def paths_overlap(first: Path, second: Path) -> bool:
            return (
                first == second
                or first in second.parents
                or second in first.parents
            )

        protected_directories = {
            "Minecraft world": self.world_directory,
            "Snapshots": self.snapshots_directory,
            "Runtime": self.runtime_directory,
        }

        for name, directory in protected_directories.items():
            if paths_overlap(self.replication_directory, directory):
                raise ValueError(
                    f"Replication directory cannot overlap the {name} directory"
                )

        if self.peer_registry is not None:
            self.peer_registry.validate_local_peer(
                self.peer_id,
                self.world_id,
            )
