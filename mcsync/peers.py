
"""Shared peer registry loading and validation for MCSync."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PeerRegistryError(ValueError):
    """Raised when the shared peer registry is invalid."""


_PEER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_HOST_LABEL_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


@dataclass(frozen=True)
class Peer:
    """One MCSync peer's network identity."""

    peer_id: str
    host: str


@dataclass(frozen=True)
class PeerRegistry:
    """Shared network configuration for one MCSync world."""

    protocol_version: int
    world_id: str
    communication_port: int
    peers: tuple[Peer, ...]

    @classmethod
    def from_file(cls, registry_path: Path) -> "PeerRegistry":
        """Load and validate a peer registry JSON file."""

        registry_path = registry_path.expanduser().resolve()

        if not registry_path.is_file():
            raise FileNotFoundError(
                f"Peer registry not found: {registry_path}"
            )

        try:
            with registry_path.open("r", encoding="utf-8") as file:
                data: Any = json.load(file)
        except json.JSONDecodeError as exc:
            raise PeerRegistryError(
                f"Invalid peer registry JSON: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise PeerRegistryError(
                "Peer registry root must be a JSON object"
            )

        required = (
            "protocol_version",
            "world_id",
            "communication_port",
            "peers",
        )

        missing = [key for key in required if key not in data]
        if missing:
            raise PeerRegistryError(
                f"Missing registry fields: {', '.join(missing)}"
            )

        raw_peers = data["peers"]

        if not isinstance(raw_peers, list):
            raise PeerRegistryError("peers must be a JSON array")

        peers: list[Peer] = []

        for index, item in enumerate(raw_peers):
            if not isinstance(item, dict):
                raise PeerRegistryError(
                    f"Peer entry {index} must be a JSON object"
                )

            if "peer_id" not in item or "host" not in item:
                raise PeerRegistryError(
                    f"Peer entry {index} requires peer_id and host"
                )

            if not isinstance(item["peer_id"], str):
                raise PeerRegistryError(
                    f"Peer entry {index} peer_id must be a string"
                )

            if not isinstance(item["host"], str):
                raise PeerRegistryError(
                    f"Peer entry {index} host must be a string"
                )

            peers.append(
                Peer(
                    peer_id=item["peer_id"],
                    host=item["host"],
                )
            )

        registry = cls(
            protocol_version=data["protocol_version"],
            world_id=data["world_id"],
            communication_port=data["communication_port"],
            peers=tuple(peers),
        )

        registry.validate()
        return registry

    @staticmethod
    def _normalize_host(host: str) -> str:
        """Normalize an IP address or hostname for comparisons."""

        host = host.strip()

        try:
            return ipaddress.ip_address(host).compressed.casefold()
        except ValueError:
            return host.rstrip(".").casefold()

    @staticmethod
    def _validate_host(host: str) -> None:
        """Reject malformed addresses and non-hostname URL values."""

        if not host or host != host.strip():
            raise PeerRegistryError(
                "Peer host cannot be empty or contain surrounding whitespace"
            )

        try:
            ipaddress.ip_address(host)
            return
        except ValueError:
            pass

        if len(host) > 253 or host.endswith("."):
            host = host[:-1] if host.endswith(".") else host

        if not host or len(host) > 253:
            raise PeerRegistryError(f"Invalid peer host: {host!r}")

        labels = host.split(".")

        if not all(_HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
            raise PeerRegistryError(f"Invalid peer host: {host!r}")

    def validate(self) -> None:
        """Validate registry-wide fields and peer identities."""

        if (
            not isinstance(self.protocol_version, int)
            or isinstance(self.protocol_version, bool)
            or self.protocol_version != 1
        ):
            raise PeerRegistryError(
                "Unsupported peer protocol_version; expected 1"
            )

        if not isinstance(self.world_id, str) or not self.world_id.strip():
            raise PeerRegistryError("world_id cannot be empty")

        if (
            not isinstance(self.communication_port, int)
            or isinstance(self.communication_port, bool)
            or not 1 <= self.communication_port <= 65535
        ):
            raise PeerRegistryError(
                "communication_port must be between 1 and 65535"
            )

        if not self.peers:
            raise PeerRegistryError("At least one peer is required")

        seen_ids: set[str] = set()
        seen_endpoints: set[tuple[str, int]] = set()

        for peer in self.peers:
            if not isinstance(peer.peer_id, str) or not _PEER_ID_PATTERN.fullmatch(
                peer.peer_id
            ):
                raise PeerRegistryError(
                    f"Invalid peer_id: {peer.peer_id!r}"
                )

            normalized_id = peer.peer_id.casefold()

            if normalized_id in seen_ids:
                raise PeerRegistryError(
                    f"Duplicate peer_id: {peer.peer_id}"
                )

            seen_ids.add(normalized_id)

            if not isinstance(peer.host, str):
                raise PeerRegistryError(
                    f"Host for {peer.peer_id} must be a string"
                )

            self._validate_host(peer.host)

            endpoint = (
                self._normalize_host(peer.host),
                self.communication_port,
            )

            if endpoint in seen_endpoints:
                raise PeerRegistryError(
                    f"Duplicate peer endpoint: {peer.host}"
                )

            seen_endpoints.add(endpoint)

    def get_peer(self, peer_id: str) -> Peer:
        """Find a peer by its ID."""

        for peer in self.peers:
            if peer.peer_id.casefold() == peer_id.casefold():
                return peer

        raise PeerRegistryError(f"Unknown peer_id: {peer_id}")

    def validate_local_peer(
        self,
        local_peer_id: str,
        expected_world_id: str,
    ) -> Peer:
        """Confirm this computer belongs to the expected peer network."""

        if self.world_id != expected_world_id:
            raise PeerRegistryError(
                f"Registry world_id {self.world_id!r} does not match "
                f"local world_id {expected_world_id!r}"
            )

        return self.get_peer(local_peer_id)
