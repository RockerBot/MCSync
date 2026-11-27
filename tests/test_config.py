
import json
import tempfile
import unittest

from dataclasses import replace
from pathlib import Path

from mcsync.config import MCSyncConfig


class ConfigTests(unittest.TestCase):

    def test_load_local_config(self):
        root = Path(__file__).resolve().parents[1]
        config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

        self.assertEqual(config.peer_id, "peer-a")
        self.assertEqual(config.world_id, "MCSyncTest")
        self.assertEqual(config.minecraft_version, "1.21.1")
        self.assertEqual(config.loader, "NeoForge")
        self.assertEqual(config.checkpoint_interval_minutes, 10)

        self.assertEqual(
            config.runtime_directory,
            config.server_directory / ".mcsync",
        )

        # self.assertEqual(
        #     config.replication_directory,
        #     root / "MCSyncData" / "replication",
        # )

        config.validate()

    def test_default_replication_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_directory = root / "config"
            server_directory = root / "server"
            world_directory = server_directory / "TestWorld"
            snapshots_directory = root / "snapshots"
            java_executable = root / "java.exe"

            config_directory.mkdir()
            world_directory.mkdir(parents=True)
            snapshots_directory.mkdir()
            java_executable.write_text("test")

            data = {
                "peer_id": "peer-a",
                "world_id": "TestWorld",
                "server_directory": "../server",
                "world_directory": "../server/TestWorld",
                "snapshots_directory": "../snapshots",
                "java_executable": "../java.exe",
                "server_start_command": ["run.bat"],
                "minecraft_version": "1.21.1",
                "loader": "NeoForge",
                "loader_version": "21.1.252",
            }

            config_path = config_directory / "local.json"
            config_path.write_text(json.dumps(data))

            config = MCSyncConfig.from_file(config_path)

            self.assertEqual(
                config.replication_directory,
                root / "MCSyncData" / "replication",
            )

    def test_replication_inside_snapshots_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

        invalid_config = replace(
            config,
            replication_directory=config.snapshots_directory / "replication",
        )

        with self.assertRaisesRegex(ValueError, "overlap"):
            invalid_config.validate()

    def test_snapshots_inside_replication_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

        invalid_config = replace(
            config,
            replication_directory=config.snapshots_directory.parent,
        )

        with self.assertRaisesRegex(ValueError, "overlap"):
            invalid_config.validate()

    def test_local_config_loads_peer_registry(self):
        root = Path(__file__).resolve().parents[1]
        config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

        self.assertIsNotNone(config.peer_registry)
        self.assertEqual(
            config.peer_registry.world_id,
            config.world_id,
        )
        self.assertEqual(
            config.peer_registry.get_peer("peer-a").host,
            "127.0.0.1",
        )

    def test_local_peer_missing_from_registry_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

        invalid_config = replace(config, peer_id="peer-z")

        with self.assertRaisesRegex(ValueError, "Unknown peer_id"):
            invalid_config.validate()

    def test_local_world_mismatch_with_registry_is_rejected(self):
        root = Path(__file__).resolve().parents[1]
        config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

        invalid_config = replace(config, world_id="AnotherWorld")

        with self.assertRaisesRegex(ValueError, "does not match"):
            invalid_config.validate()


    def test_default_secrets_file_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_directory = root / "config"
            server_directory = root / "server"
            world_directory = server_directory / "TestWorld"
            snapshots_directory = root / "snapshots"
            java_executable = root / "java.exe"

            config_directory.mkdir()
            world_directory.mkdir(parents=True)
            snapshots_directory.mkdir()
            java_executable.write_text("test")

            data = {
                "peer_id": "peer-a",
                "world_id": "TestWorld",
                "server_directory": "../server",
                "world_directory": "../server/TestWorld",
                "snapshots_directory": "../snapshots",
                "java_executable": "../java.exe",
                "server_start_command": ["run.bat"],
                "minecraft_version": "1.21.1",
                "loader": "NeoForge",
                "loader_version": "21.1.252",
            }

            config_path = config_directory / "local.json"
            config_path.write_text(json.dumps(data))

            config = MCSyncConfig.from_file(config_path)

            self.assertEqual(
                config.secrets_file,
                (config_directory / "secrets.json").resolve(),
            )

    def test_custom_secrets_file_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_directory = root / "config"
            server_directory = root / "server"
            world_directory = server_directory / "TestWorld"
            snapshots_directory = root / "snapshots"
            java_executable = root / "java.exe"

            config_directory.mkdir()
            world_directory.mkdir(parents=True)
            snapshots_directory.mkdir()
            java_executable.write_text("test")

            data = {
                "peer_id": "peer-a",
                "world_id": "TestWorld",
                "server_directory": "../server",
                "world_directory": "../server/TestWorld",
                "snapshots_directory": "../snapshots",
                "java_executable": "../java.exe",
                "server_start_command": ["run.bat"],
                "minecraft_version": "1.21.1",
                "loader": "NeoForge",
                "loader_version": "21.1.252",
                "secrets_file": "../custom/secrets.json",
            }

            config_path = config_directory / "local.json"
            config_path.write_text(json.dumps(data))

            config = MCSyncConfig.from_file(config_path)

            self.assertEqual(
                config.secrets_file,
                (root / "custom" / "secrets.json").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
