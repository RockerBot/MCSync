
"""MCSync command-line interface."""

import argparse
import json
import sys
from pathlib import Path

from mcsync.config import MCSyncConfig
from mcsync.server import ServerManager, ServerError
from mcsync.peer_monitor import inspect_all_peers
from mcsync.peer_api import PeerAPIError
from mcsync.control_api import (
    ControlAPIError,
    LocalManagerUnavailable,
    request_local_control,
)
from mcsync.host_manager import (
    HostManager,
    HostManagerError,
)
from mcsync.secrets import (
    SecretError,
    load_local_control_token,
)
from mcsync.snapshots import list_snapshots, SnapshotError
from mcsync.replication import list_verified_replicas


def print_peer_health(results):
    """Display the health of configured remote peers."""

    if not results:
        print("No remote peers are configured.")
        return

    print("\nMCSync Peer Health")
    print("==================")

    for peer in results:
        print(f"\nPeer: {peer.peer_id}")
        print(f"Address: {peer.host}")

        if not peer.reachable:
            print("Connection: UNREACHABLE")
            print(f"Error: {peer.error}")
            print("Server state: UNKNOWN")
            continue

        print("Connection: REACHABLE")

        if peer.error:
            print(f"Status error: {peer.error}")
            continue

        print(f"Minecraft: {peer.server_state}")

        if peer.latest_generation is not None:
            print(f"Latest verified replica: {peer.latest_generation}")
        else:
            print("Latest verified replica: None")

        print(f"Last observed: {peer.observed_at_utc}")


def print_generations(title, generations):
    """Display verified snapshots or replicas."""

    print()
    print(title)
    print("=" * len(title))

    if not generations:
        print("No verified generations found.")
        return

    latest_generation = generations[-1]["generation"]

    for item in generations:
        metadata = item["metadata"]
        generation = item["generation"]

        latest = " [LATEST]" if generation == latest_generation else ""

        print()
        print(f"Generation: {generation:06d}{latest}")
        print(f"Created:    {metadata.get('created_at_utc', 'Unknown')}")
        print(f"Created by: {metadata.get('created_by', 'Unknown')}")
        print(f"Files:      {metadata.get('file_count', 'Unknown')}")
        print(f"Clean stop: {metadata.get('clean_shutdown', 'Unknown')}")
        print(f"Manifest:   {metadata.get('manifest_sha256', 'Unknown')}")
        print(f"Path:       {item['path']}")

    print()
    print(f"Total verified generations: {len(generations)}")


def send_local_command(config, action):
    """Send a command to the persistent local HostManager."""

    token = load_local_control_token(config.secrets_file)

    return request_local_control(
        port=HostManager.control_port,
        token=token,
        action=action,
    )


def main():
    parser = argparse.ArgumentParser(
        description="MCSync Minecraft host manager"
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/local.json"),
        help="Path to local MCSync configuration",
    )

    parser.add_argument(
        "command",
        choices=[
            "start",
            "status",
            "stop",
            "save",
            "peers",
            "snapshots",
            "replicas",
        ],
        help="Command to execute",
    )

    args = parser.parse_args()

    try:
        config = MCSyncConfig.from_file(args.config)

        if args.command == "start":
            manager = ServerManager(config)
            host_manager = HostManager(manager)

            print("Starting persistent MCSync HostManager...")
            print("The manager will remain running until Minecraft is stopped.")
            print("Use another terminal to run status, save, or stop.")
            print("Press Ctrl+C to request a graceful shutdown.\n")

            host_manager.run()

            print("MCSync HostManager stopped.")
        elif args.command == "status":
            try:
                result = send_local_command(config, "status")
                result["manager_state"] = "MANAGER_RUNNING"
            except LocalManagerUnavailable:
                result = {
                    "manager_state": "MANAGER_STOPPED",
                    "minecraft_state": "UNKNOWN",
                    "message": (
                        "The local HostManager is not running. "
                        "Minecraft state cannot be confirmed."
                    ),
                }

            print(json.dumps(result, indent=2))

        elif args.command == "stop":
            result = send_local_command(config, "stop")
            print(json.dumps(result, indent=2))
            print("Graceful shutdown requested.")

        elif args.command == "save":
            result = send_local_command(config, "save")
            print(json.dumps(result, indent=2))
            print("Save command sent.")

        elif args.command == "peers":
            manager = ServerManager(config)
            results = inspect_all_peers(manager)
            print_peer_health(results)

        elif args.command == "snapshots":
            snapshots = list_snapshots(
                config.snapshots_directory,
                expected_world_id=config.world_id,
            )
            print_generations("Local Snapshots", snapshots)

        elif args.command == "replicas":
            replicas = list_verified_replicas(
                config.replication_directory,
                expected_world_id=config.world_id,
            )
            print_generations("Verified Replicas", replicas)

    except (
        ServerError,
        SecretError,
        SnapshotError,
        PeerAPIError,
        ControlAPIError,
        HostManagerError,
        ValueError,
        FileNotFoundError,
        OSError,
    ) as exc:
        print(f"MCSync error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
