# MCSync — Project Context & Implementation Plan

> **Purpose:** This document is the portable source of truth for the MCSync project. Keep it in the GitHub repository and attach or paste it into a new ChatGPT conversation whenever work resumes.
>
> **Repository:** https://github.com/RockerBot/MCSync  
> **Project status:** Design/planning stage. The repository was checked on 2026-11-16 and was empty at that time. No implementation or deployment is assumed to exist yet.

---

## 1. Project goal

Build a peer-hosted Minecraft server system for three friends (Players A, B and C).

The players are not always online at the same time. A permanent paid Minecraft server is becoming too expensive, so the goal is to let any of the three players host the world from their own computer:

- A can start the server and B/C can join.
- When A wants to leave, the server saves and shuts down cleanly.
- The latest world state is transferred to B and C.
- B or C can take over hosting.
- A can later synchronize the latest world and rejoin.
- Only one computer may be the authoritative host at a time.
- Windows and Linux computers must both be supported.
- All three computers are reasonably capable of running the modded server.
- The system should minimize the time between a world change and its replication to the other computers.

**Primary objective:** eliminate recurring dedicated-server hosting costs without risking world corruption or losing progress during host changes.

## 2. Confirmed requirements and decisions

| Item | Decision |
|---|---|
| Players | Three: A, B and C |
| Operating systems | Mixed Windows and Linux |
| Who can host | Any of A, B or C |
| Computer capability | All three can reasonably run the server |
| Networking | Tailscale is the proposed private network |
| File replication | Syncthing is the proposed peer-to-peer transfer layer |
| Host manager | A cross-platform Python application |
| Server ownership | Exactly one active host |
| Normal replication | Periodic safe checkpoints while the server is running |
| Initial checkpoint target | Every 10 minutes; tune after measuring |
| Handoff | Graceful shutdown, final checkpoint, verified synchronization, then ownership transfer |
| Unexpected crash | Conservative recovery; do not automatically assume the old host is dead |
| Backups | Keep at least two previous verified checkpoints, plus independent backups |
| Migration | Do not retire the existing EC2 server until peer hosting is tested successfully |

These are design decisions, not proof that the features have been implemented.

## 3. Existing Minecraft environment

Known details from previous troubleshooting:

- Minecraft Java Edition **1.21.1**
- NeoForge **21.1.252**
- Java **21**
- Existing server has been run on AWS EC2 in `ap-south-1`.
- The server has used Docker Compose with service name `mc` and image `itzg/minecraft-server`.
- Server port: `25565`.
- RCON has been configured for server administration.
- The existing world is modded and contains substantial storage systems, machines and modded content.

Known mods / mod families include:

- Applied Energistics 2 (AE2)
- AE2 add-ons, including ExtendedAE and MEGA Cells
- Mekanism
- Storage Drawers
- Industrial Foregoing
- Jade
- Farmer's Delight
- Lithium
- Gravestone mod
- Other mods; the complete current mod list still needs to be exported from the actual server.

Previous issue to keep in mind:

- There has been an intermittent client disconnect around “Loading Terrain”.
- A crash report showed an NBT allocation error close to the 2 MiB limit while receiving a chunk-with-light packet.
- Large storage systems, machines, inventories and modded block entities exist.
- Do not delete chunks, remove mods, or make destructive world changes as part of MCSync setup.
- Back up the existing world before migration or troubleshooting.

**Important:** Treat the version and environment details above as the last known information. Before migration, inspect the live server and export the exact Java version, NeoForge build, mod list, configs, datapacks, server properties and world layout.

## 4. High-level architecture

Three equal peers, no permanent central host:

```text
 Player A                    Player B                    Player C
 Windows/Linux               Windows/Linux               Windows/Linux
     |                           |                           |
     +---------------------------+---------------------------+
                                 |
                        Tailscale private network
                                 |
                    +------------+------------+
                    |                         |
              Minecraft host             Syncthing
              (one active)              replication
                    |                         |
                    +------------+------------+
                                 |
                         Python Host Manager
             ownership, snapshots, verification, handoff
```

### Components

1. **Tailscale**
   - Connects all three computers through a private network.
   - Players connect to the current host's Tailscale name/IP and port `25565`.
   - No router port forwarding should normally be necessary.
   - Prefer one shared tailnet with appropriate access controls.
   - Example device names: `minecraft-a`, `minecraft-b`, `minecraft-c`.
   - Example connection: `minecraft-a:25565` when A hosts.
   - MagicDNS can make host addresses easier to remember.

2. **Syncthing**
   - Transfers published world snapshots between peers.
   - It is a file synchronization tool, not a Minecraft-aware database replication system.
   - Do not synchronize the actively changing server world directory.
   - Use hashes/manifests and receiver-side verification; “Syncthing is up to date” alone is not enough to authorize hosting.

3. **Python Host Manager**
   - Same codebase on Windows and Linux.
   - Starts and stops the local Minecraft server.
   - Requests and publishes checkpoints.
   - Checks replication and file integrity.
   - Tracks world generation and host ownership.
   - Refuses to start if the local world is stale, incomplete, incompatible or ownership is uncertain.
   - Provides a simple CLI first; a GUI/dashboard can come later.

4. **Minecraft server**
   - Run the same Java/NeoForge server distribution on all three computers.
   - Do not require Docker for the first version; native Java execution is simpler across Windows and Linux.
   - Keep server-specific launch scripts for Windows and Linux.

## 5. Active world vs replication copy

Each computer must distinguish between:

- **Active world:** The world directory currently opened by the Minecraft server. Only the active host may modify it.
- **Replication copy:** A stable, completed checkpoint that Syncthing can transfer to other peers.

Never point Syncthing at the active world directory.

Suggested layout (exact paths can be adapted per operating system):

```text
MCSync/
├── server/
│   ├── mods/
│   ├── config/
│   ├── defaultconfigs/
│   ├── libraries/
│   ├── run.sh
│   ├── run.bat
│   └── world/                 # active world; NOT synchronized live
│
├── replication/
│   ├── world/                 # stable published snapshot
│   └── metadata/
│       ├── READY.json
│       └── manifest.json
│
├── backups/                   # local independent recovery copies
│
└── manager/
    ├── manager.py
    ├── config.example.json
    ├── logs/
    └── README.md
```

Do not commit the actual world, backups, server JARs, mod JARs, credentials, Tailscale state, Syncthing private keys or RCON secrets to the public Git repository.

## 6. Safe checkpoint design

### Target behaviour

- Initial checkpoint interval: **10 minutes**.
- Checkpointing should minimize interruption to gameplay.
- A checkpoint is not considered available until it has been completely copied and verified.
- A graceful host handoff always creates a final checkpoint after the server has stopped.
- Keep at least two previous verified checkpoints; maintain additional independent backups.

### Important consistency warning

A Minecraft world is not a single file. Region files, player data, dimensions, mod data and other files can be updated at different times. Copying the live world folder while the server is writing to it can produce an inconsistent snapshot.

`save-all flush` forces pending world saves to disk, but by itself it does **not** make an arbitrary live file copy safe while the server continues running.

Possible checkpoint approaches, in order of safety:

1. **Initial reliable implementation:** use a short controlled save pause or clean shutdown around snapshot creation. Validate the exact method against this modpack.
2. **Later optimization:** use a filesystem-native consistent snapshot (for example, VSS on Windows or LVM/ZFS/Btrfs snapshots on supported Linux filesystems), if practical and tested.
3. Do not claim a cross-platform live snapshot is safe until it has been tested with the actual server and mods.

If using a save-pause approach, the implementation must carefully coordinate the server console:
- Prevent normal world saving using the appropriate server command.
- Flush pending saves.
- Copy the complete required data to a staging directory.
- Resume saving immediately after the copy is complete.
- Handle errors so saving is always re-enabled.
- Test player data and mod data, not just region files.

A clean server shutdown remains the safest final handoff checkpoint.

### Publish and verify

A robust publication flow:

1. Create the snapshot in a staging directory outside the Syncthing folder.
2. Ensure the snapshot operation completed successfully.
3. Generate a manifest containing relative paths, sizes and SHA-256 hashes.
4. Publish the completed snapshot to the replication directory.
5. Publish metadata describing the generation.
6. Allow Syncthing to transfer the files.
7. On the receiving peer, wait for synchronization to settle and verify every file against the manifest.
8. Mark the generation locally as verified only after all checks pass.

Do not rely on file arrival order. A `READY.json` marker might arrive before some other files; the receiver must verify the manifest before accepting the generation.

### Generation metadata

Example only:

```json
{
  "world_id": "main-world",
  "generation": 142,
  "parent_generation": 141,
  "created_by": "player-a",
  "created_at": "2026-11-16T12:00:00Z",
  "minecraft_version": "1.21.1",
  "loader": "NeoForge",
  "loader_version": "21.1.252",
  "clean_shutdown": false,
  "manifest_sha256": "REPLACE_WITH_REAL_HASH"
}
```

The actual implementation should define a strict schema and validate it. Generation numbers must increase monotonically. A peer must never replace a newer accepted generation with an older one.

## 7. Host ownership and split-brain prevention

This is a critical safety requirement.

A disconnected host may still be running Minecraft. A network timeout does not prove the old server has stopped. Therefore a simple expiring lock or heartbeat is not sufficient to guarantee that two hosts cannot run concurrently.

### Graceful handoff

Example: A is hosting and wants B to take over.

1. A requests a handoff to B.
2. A tells Minecraft to save and stop.
3. The manager waits for the Java server process to exit.
4. A creates the final clean-shutdown snapshot.
5. A publishes the final generation and manifest.
6. B waits for Syncthing to finish and verifies the generation.
7. Ownership is transferred.
8. B installs the verified generation as its active world.
9. B starts the Minecraft server.
10. A and C connect to B.

### Unexpected host failure

For the first release, use conservative manual recovery:

- Do not automatically take ownership just because the old host disappears from Tailscale.
- Ask the remaining players to confirm that the old server is stopped or otherwise fenced off.
- Select the newest fully verified generation.
- Preserve the failed host's local files for possible recovery.
- Start only one replacement host.

Strong automatic crash failover requires a reliable fencing/quorum mechanism or an independent coordinator. Three intermittently connected peers cannot safely infer global ownership from local observations alone.

### Ownership state

The manager should have explicit states, for example:

- `STOPPED`
- `HOSTING`
- `CHECKPOINTING`
- `REPLICATING`
- `READY`
- `HANDOFF_PENDING`
- `RECOVERY_REQUIRED`
- `ERROR`

The manager must fail closed: if ownership or world freshness is uncertain, do not start the server.

## 8. Server compatibility and modpack manifest

All three computers must use compatible, preferably identical:

- Java major version and runtime
- Minecraft version
- NeoForge version
- Server JAR / server distribution
- Mods and mod versions
- Config files
- Default configs
- Datapacks
- Server properties relevant to world behaviour

Create a `modpack-manifest.json` with hashes for the relevant files. The manager should compare local files before allowing a host to start.

Do not synchronize `mods/`, `config/` or server binaries as part of the world replication mechanism. Distribute those through a controlled release or setup process so all peers run the same server environment.

## 9. Suggested Python Host Manager responsibilities

Initial functions/modules:

| Function | Responsibility |
|---|---|
| `start_server()` | Validate compatibility, ownership and world generation, then launch Minecraft |
| `stop_server()` | Save and stop Minecraft gracefully |
| `create_snapshot()` | Create a consistent checkpoint |
| `publish_snapshot()` | Publish completed snapshot and manifest |
| `sync_status()` | Query or inspect Syncthing status |
| `verify_snapshot()` | Verify generation, metadata and file hashes |
| `acquire_host()` | Request/validate exclusive host ownership |
| `release_host()` | Release ownership only after clean shutdown and final publication |
| `get_network_status()` | Show peers and their availability |
| `recover_world()` | Restore a previous verified backup |
| `check_modpack()` | Compare local installation with shared manifest |

### Cross-platform requirements

- Use Python 3 and the standard library where possible.
- Use `pathlib` for paths.
- Avoid hard-coded Windows or Linux paths.
- Use `subprocess` safely and handle process termination.
- Provide Windows and Linux launch wrappers only where needed.
- Never put secrets in source control.
- Log all ownership, snapshot, verification and recovery events.
- Prefer a CLI for the first release; add a GUI only after the core safety logic works.

## 10. Expected user workflow

### Start hosting

1. Open MCSync.
2. Check peer and synchronization status.
3. Choose **Start hosting**.
4. Manager verifies ownership, modpack and latest world generation.
5. Manager prepares the active world and starts Minecraft.
6. Manager displays the address for the other players.

### Join another host

1. Open MCSync or read the current host status.
2. Connect to the current host's Tailscale DNS name/IP on port `25565`.

### Hand off hosting

1. Current host chooses **Transfer hosting** and selects a peer.
2. Current host saves and stops Minecraft.
3. Final snapshot is created and replicated.
4. New host verifies it and takes ownership.
5. New host starts Minecraft.
6. Other players reconnect to the new host.

### Return after being offline

1. Start Tailscale and Syncthing.
2. Wait for the latest generation to arrive.
3. Verify it.
4. Join the current host, or request hosting if no one is hosting.

## 11. Failure handling requirements

| Situation | Required behaviour |
|---|---|
| Another player is hosting | Refuse local start; show current host |
| Sync is incomplete | Refuse start |
| Manifest/hash mismatch | Refuse start; preserve files for diagnosis |
| Local generation is older | Do not host from it |
| Two players request hosting | Only one may proceed; other request is rejected |
| Host shuts down normally | Final save, stop, checkpoint, verify, handoff |
| Host crashes | Manual recovery/fencing; never assume timeout means stopped |
| Snapshot creation fails | Resume server saving if paused; do not publish snapshot |
| Disk runs out of space | Stop snapshot safely, report error, preserve last good generation |
| Modpack mismatch | Refuse start and explain differences |
| Peer was offline | It downloads latest generation before it can host |
| Corrupt new generation | Fall back to previous verified backup after explicit recovery |

## 12. Repository plan

GitHub repository: https://github.com/RockerBot/MCSync

Recommended repository layout:

```text
MCSync/
├── README.md
├── PROJECT_CONTEXT.md
├── LICENSE
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SAFETY_AND_RECOVERY.md
│   └── SETUP_WINDOWS_LINUX.md
├── mcsync/
│   ├── __init__.py
│   ├── cli.py
│   ├── manager.py
│   ├── server.py
│   ├── snapshots.py
│   ├── replication.py
│   ├── ownership.py
│   ├── verification.py
│   └── config.py
├── config/
│   └── config.example.json
├── scripts/
│   ├── install-windows.ps1
│   └── install-linux.sh
└── tests/
```

### Git safety

The Git repository should contain source code, documentation, templates and tests—not the private Minecraft world or machine-specific state.

Suggested `.gitignore` entries:

```gitignore
# Actual server/world data
server/
world/
backups/
replication/
*.mca
*.mcr
*.dat
*.dat_old

# Runtime state and logs
logs/
*.log
*.pid
*.lock
state/
runtime/

# Secrets and local config
.env
.env.*
config.json
*.secret
secrets/
*.key
*.pem

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/

# OS/editor
.DS_Store
Thumbs.db
.vscode/
.idea/
```

Review `.gitignore` carefully before the first commit. Do not commit:
- World saves or player data
- Backups or snapshots
- Server JARs or mod JARs
- RCON passwords
- Tailscale auth keys or state
- Syncthing private keys or device credentials
- Personal IPs or private configuration

Use `config.example.json` with placeholders and keep each person's real config local.

## 13. Implementation roadmap

### Phase 0 — Inventory and backup
- Inspect the current EC2 server.
- Export the exact server version, Java version, NeoForge version, mod list and configs.
- Identify all world folders and mod-specific persistent data.
- Make and test an independent backup.
- Record current world size and typical changed-file volume.

### Phase 1 — Peer networking
- Install Tailscale on A, B and C.
- Install Syncthing on A, B and C.
- Connect all peers.
- Confirm direct or relay connectivity and test transfer of large files.
- Set up the shared replication folder.
- Confirm the active world folder is not being synchronized.

### Phase 2 — Snapshot prototype
- Implement a controlled checkpoint for the actual modded server.
- Test save pause / flush / copy / resume behaviour, or use clean shutdown if needed.
- Generate manifests and SHA-256 hashes.
- Replicate and verify snapshots.
- Test interrupted transfers and recovery.

### Phase 3 — Basic host manager
- Implement configuration and cross-platform paths.
- Implement server start/stop.
- Implement modpack validation.
- Implement generation validation.
- Implement safe ownership states.
- Start with a CLI.

### Phase 4 — Graceful handoff
- Test A → B, B → C, C → A.
- Verify player inventories, dimensions, machines, AE2 networks, storage and modded data.
- Test reconnecting clients.
- Test an offline peer catching up.

### Phase 5 — Recovery and hardening
- Test host crash and network partition scenarios.
- Test corrupt/incomplete snapshots.
- Test stale generations.
- Test simultaneous start requests.
- Add backups, logs, retention and documentation.
- Do not enable automatic crash failover until safe fencing is designed and tested.

### Phase 6 — Production migration
- Migrate a copy of the real world first.
- Run the peer system in parallel with the existing EC2 server for testing.
- Only retire EC2 after repeated successful handoffs and verified backups.

## 14. Open questions / decisions still required

These should be answered during implementation, not guessed:

1. Exact Windows/Linux version and hardware details for A, B and C.
2. Exact current EC2 server directory and world name.
3. Exact complete mod list and server configuration.
4. World size and typical upload/download speeds for each player.
5. Whether all three players can install Tailscale and Syncthing.
6. Whether the project will use a simple CLI first (recommended) or require a GUI immediately.
7. How host ownership should be coordinated securely without a permanent always-on coordinator.
8. Whether the selected snapshot method is sufficiently consistent for all mods in this pack.

## 15. Useful upstream documentation

- MCSync repository: https://github.com/RockerBot/MCSync
- Tailscale downloads: https://tailscale.com/download
- Tailscale documentation: https://tailscale.com/kb/
- Syncthing downloads: https://syncthing.net/downloads/
- Syncthing documentation: https://docs.syncthing.net/
- NeoForge documentation: https://docs.neoforged.net/
- Minecraft server commands reference: https://minecraft.wiki/w/Commands

---

# Starting a new ChatGPT conversation

When resuming work, attach this file or paste the following prompt:

> We are continuing the MCSync project. Read `PROJECT_CONTEXT.md` completely and treat it as the project handoff document.
>
> MCSync is a peer-hosted Minecraft server system for three players (A, B and C), using mixed Windows/Linux computers. Any player can host, but only one host may run the authoritative world at a time. The design currently proposes Tailscale for private networking, Syncthing for replication of verified snapshots, and a cross-platform Python Host Manager.
>
> The existing world is Minecraft 1.21.1, NeoForge 21.1.252, Java 21, and heavily modded. The old server has run on AWS EC2 using Docker Compose and `itzg/minecraft-server`. Do not assume the existing server has been migrated or that any MCSync feature has been implemented.
>
> Repository: https://github.com/RockerBot/MCSync
>
> Continue from the current implementation phase. First inspect the repository and existing code before proposing edits. Keep Windows and Linux support. Prioritize data safety, verified snapshots, monotonically increasing world generations, exclusive host ownership, graceful handoff and tested recovery. Never synchronize the live active world directly. Never commit world data, backups, credentials, server JARs or mod JARs to Git.
>
> Before making destructive changes, explain the risk and ensure a verified backup exists. Clearly distinguish implemented features from proposed features. Give commands with the operating system and directory where each command should be run. Keep this document updated when important architecture or implementation decisions change.
