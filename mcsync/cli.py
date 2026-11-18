
"""MCSync command-line interface."""

import argparse
import json
import sys
from pathlib import Path

from mcsync.config import MCSyncConfig
from mcsync.server import ServerManager, ServerError
from mcsync.peer_monitor import inspect_all_peers
from mcsync.secrets import SecretError
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
        manager = ServerManager(config)

        if args.command == "start":
            server = manager.start()
            print(f"Minecraft process started. PID: {server.pid}")
            print(f"Log: {server.log_path}")

        elif args.command == "status":
            print(json.dumps(manager.status(), indent=2))

        elif args.command == "stop":
            manager.stop()
            print("Minecraft stopped successfully.")

        elif args.command == "save":
            manager.send_command("save-all flush")
            print("Save command sent.")

        elif args.command == "peers":
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
        ValueError,
        FileNotFoundError,
        OSError,
    ) as exc:
        print(f"MCSync error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
