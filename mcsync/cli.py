
"""MCSync command-line interface."""

import argparse
import json
import sys
from pathlib import Path

from mcsync.config import MCSyncConfig
from mcsync.server import ServerManager, ServerError
from mcsync.checkpoint import create_checkpoint, wait_for_remote_save, CheckpointError
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
from mcsync.replication import (
    list_verified_replicas,
    import_incoming_snapshots,
)


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
        port=config.control_port,
        token=token,
        action=action,
    )

def server_handler(args, config):
    if args.subcommand == 'start':
        manager = ServerManager(config)
        host_manager = HostManager(manager)

        print("Starting persistent MCSync HostManager...")
        print("The manager will remain running until Minecraft is stopped.")
        print("Use another terminal to run status, save, or stop.")
        print("Press Ctrl+C to request a graceful shutdown.\n")

        host_manager.run()

        print("MCSync HostManager stopped.")

    elif args.subcommand == 'status':
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

    elif args.subcommand == 'stop':
        result = send_local_command(config, "stop")
        print(json.dumps(result, indent=2))
        print("Graceful shutdown requested.")

    elif args.subcommand == 'save':
        result = send_local_command(config, "save")
        print(json.dumps(result, indent=2))
        print("Save command sent.")


def snapshot_handler(args, config):
    if args.subcommand == 'list':
        snapshots = list_snapshots(
            config.snapshots_directory,
            expected_world_id=config.world_id,
        )
        print_generations("Local Snapshots", snapshots)

    elif args.subcommand == 'create':
        try:
            server_status = send_local_command(config, 'status')
        except LocalManagerUnavailable as e:
            server_status = {'state': 'STOPPED'}

        if server_status['state'] == 'RUNNING':
            log_path = Path(server_status['log_file'])

            try:
                log_offset = log_path.stat().st_size
            except OSError as exc:
                raise CheckpointError(
                    f"Could not inspect the Minecraft log: {exc}"
                ) from exc

            send_local_command(config, 'save')
            token = load_local_control_token(config.secrets_file)
            wait_for_remote_save(config, token, log_path, log_offset, timeout=180)

        result = create_checkpoint(config, created_by=config.peer_id)

        print("\nCHECKPOINT SUCCESSFUL")
        print(f"Generation: {result.generation}")
        print(f"Snapshot: {result.snapshot_directory}")
        print(f"Replica: {result.replica_directory}")
        if result.replication_error is not None:
            print(f"Replication error: {result.replication_error}")
        # print(f"Restarted: {result.restarted}")


    elif args.subcommand == 'import':
        results = import_incoming_snapshots(
            config.incoming_directory,
            config.replication_directory,
            expected_world_id=config.world_id,
        )

        print("\nIncoming Snapshot Import")
        print("========================")

        if not results:
            print("No incoming generation folders found.")
        else:
            for result in results:
                print()
                print(f"Generation: {result['generation']}")
                print(f"Status:     {result['status']}")

                if result["path"] is not None:
                    print(f"Path:       {result['path']}")

                if result["error"]:
                    print(f"Error:      {result['error']}")

            imported = sum(
                result["status"] == "IMPORTED"
                for result in results
            )
            already_present = sum(
                result["status"] == "ALREADY_PRESENT"
                for result in results
            )
            rejected = sum(
                result["status"] == "REJECTED"
                for result in results
            )

            print("\nImport Summary")
            print("--------------")
            print(f"Imported:        {imported}")
            print(f"Already present: {already_present}")
            print(f"Rejected:        {rejected}")

def replica_handler(args, config):
    if args.subcommand == 'list':
        replicas = list_verified_replicas(
            config.replication_directory,
            expected_world_id=config.world_id,
        )
        print_generations("Verified Replicas", replicas)


def peer_handler(args, config):
    if args.subcommand == 'list':
        manager = ServerManager(config)
        results = inspect_all_peers(manager)
        print_peer_health(results)

def main():
    '''
    cli server start
    cli server stop
    cli server save
    cli server status
    cli snapshot [list]
    cli snapshot import
    cli snapshot create
    cli replica [list]
    cli peer [list]
    '''

    parser = argparse.ArgumentParser(
        description="MCSync Minecraft host manager"
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/local.json"),
        help="Path to local MCSync configuration",
    )

    subparsers = parser.add_subparsers()

    snapshot_parser = subparsers.add_parser("snapshot", description='Snapshot related commands. Defaults to listing all snapshots.')
    snapshot_parser.add_argument('subcommand', choices = ['list', 'import', 'create'], default='list', nargs='?')
    snapshot_parser.set_defaults(run=snapshot_handler)

    start_parser = subparsers.add_parser("server", description='Commands for interacting with the minecraft server process. Defaults to showing its current status.')
    start_parser.add_argument('subcommand', choices = ['start', 'status', 'stop', 'save'], default='status', nargs='?')
    start_parser.set_defaults(run=server_handler)

    replica_parser = subparsers.add_parser("replica", description='Replica related commands. Defaults to listing all replicas.')
    replica_parser.add_argument('subcommand', choices = ['list'], default='list', nargs='?')
    replica_parser.set_defaults(run=replica_handler)

    peer_parser = subparsers.add_parser("peer", description='Peer related commands. Defaults to listing all peers.')
    peer_parser.add_argument('subcommand', choices = ['list'], default='list', nargs='?')
    peer_parser.set_defaults(run=peer_handler)

    args = parser.parse_args()

    try:
        config = MCSyncConfig.from_file(args.config)
        args.run(args, config)

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
