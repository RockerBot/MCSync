
"""Read-only health monitoring for configured MCSync peers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from mcsync.peer_api import PeerAPIError, request_peer_status
from mcsync.secrets import load_peer_token


@dataclass(frozen=True)
class PeerHealth:
    """Observed health of one configured peer."""

    peer_id: str
    host: str
    reachable: bool
    observed_at_utc: str
    server_state: str | None = None
    latest_generation: int | None = None
    error: str | None = None
    status: dict | None = None


def inspect_peer(
    peer,
    port: int,
    auth_token: str,
    expected_world_id: str,
    timeout: float = 5,
) -> PeerHealth:
    """Query one peer and return its observed health."""

    observed_at = datetime.now(timezone.utc).isoformat()

    try:
        status = request_peer_status(
            peer=peer,
            port=port,
            auth_token=auth_token,
            expected_world_id=expected_world_id,
            timeout=timeout,
        )

    except (PeerAPIError, OSError, ValueError) as exc:
        return PeerHealth(
            peer_id=peer.peer_id,
            host=peer.host,
            reachable=False,
            observed_at_utc=observed_at,
            error=str(exc),
        )

    server = status.get("server")

    if not isinstance(server, dict):
        return PeerHealth(
            peer_id=peer.peer_id,
            host=peer.host,
            reachable=True,
            observed_at_utc=observed_at,
            error="Peer returned an invalid server status",
            status=status,
        )

    state = server.get("state")

    if not isinstance(state, str):
        return PeerHealth(
            peer_id=peer.peer_id,
            host=peer.host,
            reachable=True,
            observed_at_utc=observed_at,
            error="Peer returned an invalid server state",
            status=status,
        )

    replica = status.get("latest_verified_replica")
    generation = None

    if isinstance(replica, dict):
        value = replica.get("generation")
        if isinstance(value, int) and not isinstance(value, bool):
            generation = value

    return PeerHealth(
        peer_id=peer.peer_id,
        host=peer.host,
        reachable=True,
        observed_at_utc=observed_at,
        server_state=state,
        latest_generation=generation,
        status=status,
    )



def inspect_all_peers(
    manager,
    auth_token: str | None = None,
    timeout: float = 5,
) -> list[PeerHealth]:
    """Inspect every other peer in the local peer registry."""

    config = manager.config
    registry = config.peer_registry

    if registry is None:
        raise ValueError("A peer registry is required")

    # Load the shared token from the local secrets file if not supplied.
    if auth_token is None:
        if config.secrets_file is None:
            raise ValueError("A secrets file is required")

        auth_token = load_peer_token(config.secrets_file)

    results = []

    for peer in registry.peers:
        if peer.peer_id.casefold() == config.peer_id.casefold():
            continue

        results.append(
            inspect_peer(
                peer=peer,
                port=registry.communication_port,
                auth_token=auth_token,
                expected_world_id=config.world_id,
                timeout=timeout,
            )
        )

    return results
