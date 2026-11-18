
import hashlib
import json
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace

from mcsync.ownership import OwnershipLock
from mcsync.recovery import RecoveryError, recover_world
from mcsync.replication import publish_snapshot
from unittest.mock import patch


class RecoveryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.world_id = "RecoveryTest"

        self.world_directory = self.root / "server" / self.world_id
        self.snapshots_directory = self.root / "snapshots"
        self.replication_directory = self.root / "replication"

        self.world_directory.mkdir(parents=True)

        (self.world_directory / "level.dat").write_bytes(
            b"old-world"
        )

        self.lock = OwnershipLock(
            self.root / "runtime" / "ownership.lock"
        )

        self.manager = SimpleNamespace(
            config=SimpleNamespace(
                world_id=self.world_id,
                world_directory=self.world_directory,
                replication_directory=self.replication_directory,
                validate=lambda: None,
            ),
            server=None,
            ownership_lock=self.lock,
            _retain_ownership=False,
        )

    def tearDown(self):
        self.lock.release()
        self.temp.cleanup()

    def create_replica(self, generation, world_data):
        """Create a valid snapshot and publish its replica."""

        snapshot = (
            self.snapshots_directory
            / f"generation-{generation:06d}"
        )

        world_copy = snapshot / "world" / self.world_id
        world_copy.mkdir(parents=True)

        world_file = world_copy / "level.dat"
        world_file.write_bytes(world_data)

        manifest = [{
            "path": "level.dat",
            "size": len(world_data),
            "sha256": hashlib.sha256(world_data).hexdigest().upper(),
        }]

        manifest_bytes = (
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")

        (snapshot / "manifest.json").write_bytes(manifest_bytes)

        metadata = {
            "world_id": self.world_id,
            "generation": generation,
            "clean_shutdown": True,
            "file_count": 1,
            "manifest_sha256": hashlib.sha256(
                manifest_bytes
            ).hexdigest().upper(),
        }

        (snapshot / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )

        return publish_snapshot(
            snapshot,
            self.replication_directory,
            expected_world_id=self.world_id,
        )

    def test_recovers_latest_verified_replica(self):
        self.create_replica(1, b"generation-one")
        self.create_replica(2, b"generation-two")

        result = recover_world(self.manager)

        self.assertEqual(result.generation, 2)

        self.assertEqual(
            (self.world_directory / "level.dat").read_bytes(),
            b"generation-two",
        )

        self.assertTrue(self.lock.is_held)
        self.assertTrue(self.manager._retain_ownership)

    def test_recovers_selected_older_generation(self):
        older = self.create_replica(1, b"generation-one")
        self.create_replica(2, b"generation-two")

        result = recover_world(
            self.manager,
            replica_directory=older,
        )

        self.assertEqual(result.generation, 1)

        self.assertEqual(
            (self.world_directory / "level.dat").read_bytes(),
            b"generation-one",
        )

    def test_preserves_previous_world_as_backup(self):
        replica = self.create_replica(1, b"recovered-world")

        result = recover_world(
            self.manager,
            replica_directory=replica,
        )

        self.assertIsNotNone(result.backup_directory)

        self.assertTrue(result.backup_directory.is_dir())

        self.assertEqual(
            (result.backup_directory / "level.dat").read_bytes(),
            b"old-world",
        )

        self.assertEqual(
            (self.world_directory / "level.dat").read_bytes(),
            b"recovered-world",
        )

    def test_refuses_recovery_without_verified_replica(self):
        with self.assertRaises(RecoveryError):
            recover_world(self.manager)

        self.assertEqual(
            (self.world_directory / "level.dat").read_bytes(),
            b"old-world",
        )

        self.assertFalse(self.lock.is_held)

    def test_refuses_recovery_while_server_is_running(self):
        self.manager.server = SimpleNamespace(
            is_running=True
        )

        with self.assertRaises(RecoveryError):
            recover_world(self.manager)

        self.assertFalse(self.lock.is_held)

    def test_restores_previous_world_if_installation_fails(self):
        replica = self.create_replica(1, b"recovered-world")

        path_type = type(self.world_directory)
        original_rename = path_type.rename

        def fail_install(source, target):
            source = Path(source)
            target = Path(target)

            # Simulate failure when installing the staged recovered world.
            if (
                ".mcsync-recovery-" in str(source)
                and target == self.world_directory
            ):
                raise OSError("Simulated installation failure")

            return original_rename(source, target)

        with patch.object(
            path_type,
            "rename",
            autospec=True,
            side_effect=fail_install,
        ):
            with self.assertRaises(RecoveryError):
                recover_world(
                    self.manager,
                    replica_directory=replica,
                )

        # The original world must have been restored.
        self.assertTrue(self.world_directory.exists())
        self.assertEqual(
            (self.world_directory / "level.dat").read_bytes(),
            b"old-world",
        )

        # The newly acquired ownership lock should be released.
        self.assertFalse(self.lock.is_held)

    def test_retains_backup_and_ownership_if_rollback_fails(self):
        replica = self.create_replica(1, b"recovered-world")

        path_type = type(self.world_directory)
        original_rename = path_type.rename

        def fail_install_and_rollback(source, target):
            source = Path(source)
            target = Path(target)

            # Fail when installing the recovered world.
            if (
                ".mcsync-recovery-" in str(source)
                and target == self.world_directory
            ):
                raise OSError("Simulated installation failure")

            # Also fail when restoring the original world.
            if (
                ".backup-" in str(source)
                and target == self.world_directory
            ):
                raise OSError("Simulated rollback failure")

            return original_rename(source, target)

        with patch.object(
            path_type,
            "rename",
            autospec=True,
            side_effect=fail_install_and_rollback,
        ):
            with self.assertRaises(RecoveryError) as context:
                recover_world(
                    self.manager,
                    replica_directory=replica,
                )

        # The original world must remain safely stored in its backup.
        backups = list(
            self.world_directory.parent.glob(
                f"{self.world_directory.name}.backup-*"
            )
        )
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            (backups[0] / "level.dat").read_bytes(),
            b"old-world",
        )

        # The active world should not contain a partial installation.
        self.assertFalse(self.world_directory.exists())

        # Ownership must be retained because recovery is unresolved.
        self.assertTrue(self.lock.is_held)
        self.assertTrue(self.manager._retain_ownership)

        # The error should identify the backup location.
        self.assertIn(str(backups[0]), str(context.exception))

if __name__ == "__main__":
    unittest.main()
