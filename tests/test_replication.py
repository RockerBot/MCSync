
import tempfile
import unittest
import shutil

from pathlib import Path

from mcsync.replication import (
    SnapshotError,
    publish_snapshot,
    verify_replica,
    list_verified_replicas,
    get_latest_verified_replica,
    import_incoming_snapshots,
)
from mcsync.snapshots import create_snapshot


class ReplicationTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.world_id = "ReplicationTest"

        self.world_directory = self.root / "server" / self.world_id
        self.snapshots_directory = self.root / "snapshots"
        self.replication_directory = self.root / "replication"
        self.incoming_directory = self.root / "incoming"

        self.world_directory.mkdir(parents=True)

        (self.world_directory / "level.dat").write_bytes(
            b"test-world-data"
        )

        (self.world_directory / "region").mkdir()
        (self.world_directory / "region" / "r.0.0.mca").write_bytes(
            b"region-data"
        )

        self.config = type("TestConfig", (), {
            "world_id": self.world_id,
            "world_directory": self.world_directory,
            "snapshots_directory": self.snapshots_directory,
            "server_directory": self.root / "server",
            "runtime_directory": self.root / "server" / ".mcsync",
            "java_executable": "java",
            "minecraft_version": "1.21.1",
            "loader": "NeoForge",
            "loader_version": "21.1.252",
            "validate": lambda self: None,
        })()

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_test_snapshot(self):
        return create_snapshot(
            self.config,
            created_by="peer-a",
            clean_shutdown=True,
        )

    def test_publish_snapshot(self):
        snapshot = self.create_test_snapshot()

        published = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        self.assertTrue(published.is_dir())
        self.assertEqual(
            published.name,
            snapshot.name,
        )

        metadata = verify_replica(
            published,
            self.world_id,
        )

        self.assertEqual(metadata["generation"], 1)

    def test_published_replica_matches_source(self):
        snapshot = self.create_test_snapshot()

        published = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        source_metadata = verify_replica(
            snapshot,
            self.world_id,
        )

        replica_metadata = verify_replica(
            published,
            self.world_id,
        )

        self.assertEqual(
            source_metadata["manifest_sha256"],
            replica_metadata["manifest_sha256"],
        )

    def test_identical_generation_is_not_overwritten(self):
        snapshot = self.create_test_snapshot()

        first = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        second = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(first, second)

    def test_corrupt_existing_replica_is_not_overwritten(self):
        snapshot = self.create_test_snapshot()

        published = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        (published / "world" / self.world_id / "level.dat").write_bytes(
            b"corrupted"
        )

        with self.assertRaises(SnapshotError):
            publish_snapshot(
                snapshot,
                self.replication_directory,
                self.world_id,
            )

    def test_incomplete_replica_is_not_listed(self):
        snapshot = self.create_test_snapshot()

        published = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        (published / "world" / self.world_id / "level.dat").unlink()

        replicas = list_verified_replicas(
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(replicas, [])

    def test_latest_verified_replica(self):
        first = self.create_test_snapshot()

        (self.world_directory / "level.dat").write_bytes(
            b"updated-world-data"
        )

        second = self.create_test_snapshot()

        publish_snapshot(
            first,
            self.replication_directory,
            self.world_id,
        )

        publish_snapshot(
            second,
            self.replication_directory,
            self.world_id,
        )

        latest = get_latest_verified_replica(
            self.replication_directory,
            self.world_id,
        )

        self.assertIsNotNone(latest)
        self.assertEqual(latest["generation"], 2)

    def test_no_verified_replicas_returns_none(self):
        latest = get_latest_verified_replica(
            self.replication_directory,
            self.world_id,
        )

        self.assertIsNone(latest)

    def test_wrong_world_id_is_rejected(self):
        snapshot = self.create_test_snapshot()

        with self.assertRaises(SnapshotError):
            publish_snapshot(
                snapshot,
                self.replication_directory,
                "AnotherWorld",
            )

    def test_staging_directories_are_ignored(self):
        self.replication_directory.mkdir(parents=True)

        staging = self.replication_directory / ".staging-generation-000001"
        staging.mkdir()
        (staging / "partial.dat").write_bytes(b"incomplete")

        replicas = list_verified_replicas(
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(replicas, [])


    def copy_snapshot_to_incoming(self, snapshot):
        self.incoming_directory.mkdir(parents=True, exist_ok=True)

        destination = self.incoming_directory / snapshot.name

        shutil.copytree(snapshot, destination)

        return destination

    def test_import_valid_incoming_snapshot(self):
        snapshot = self.create_test_snapshot()
        incoming = self.copy_snapshot_to_incoming(snapshot)

        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "IMPORTED")
        self.assertEqual(results[0]["generation"], incoming.name)

        published = self.replication_directory / incoming.name

        self.assertTrue(published.is_dir())
        verify_replica(published, self.world_id)

        # Import must not modify or remove the incoming copy.
        self.assertTrue(incoming.is_dir())

    def test_incomplete_incoming_snapshot_is_rejected(self):
        snapshot = self.create_test_snapshot()
        incoming = self.copy_snapshot_to_incoming(snapshot)

        (incoming / "world" / self.world_id / "level.dat").unlink()

        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "REJECTED")
        self.assertFalse(
            (self.replication_directory / incoming.name).exists()
        )

    def test_corrupt_incoming_snapshot_is_rejected(self):
        snapshot = self.create_test_snapshot()
        incoming = self.copy_snapshot_to_incoming(snapshot)

        level_file = incoming / "world" / self.world_id / "level.dat"
        level_file.write_bytes(b"corrupted-data")

        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(results[0]["status"], "REJECTED")
        self.assertFalse(
            (self.replication_directory / incoming.name).exists()
        )

    def test_import_continues_after_rejected_generation(self):
        first = self.create_test_snapshot()

        (self.world_directory / "level.dat").write_bytes(
            b"second-generation"
        )

        second = self.create_test_snapshot()

        first_incoming = self.copy_snapshot_to_incoming(first)
        second_incoming = self.copy_snapshot_to_incoming(second)

        # Make generation 1 incomplete, while generation 2 remains valid.
        (first_incoming / "world" / self.world_id / "level.dat").unlink()

        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["status"], "REJECTED")
        self.assertEqual(results[1]["status"], "IMPORTED")

        self.assertFalse(
            (self.replication_directory / first_incoming.name).exists()
        )
        self.assertTrue(
            (self.replication_directory / second_incoming.name).is_dir()
        )

    def test_importing_same_generation_twice_is_idempotent(self):
        snapshot = self.create_test_snapshot()
        self.copy_snapshot_to_incoming(snapshot)

        first_results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        second_results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(first_results[0]["status"], "IMPORTED")
        self.assertEqual(second_results[0]["status"], "ALREADY_PRESENT")

    def test_import_does_not_overwrite_conflicting_generation(self):
        snapshot = self.create_test_snapshot()

        # Publish the original generation first.
        published = publish_snapshot(
            snapshot,
            self.replication_directory,
            self.world_id,
        )

        # Create a conflicting incoming copy with the same generation number.
        incoming = self.copy_snapshot_to_incoming(snapshot)

        level_file = incoming / "world" / self.world_id / "level.dat"
        level_file.write_bytes(b"different-but-invalid-data")

        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(results[0]["status"], "REJECTED")

        # The original trusted replica must remain intact.
        verify_replica(published, self.world_id)

    def test_missing_incoming_directory_returns_empty_list(self):
        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(results, [])

    def test_incoming_staging_directories_are_ignored(self):
        self.incoming_directory.mkdir(parents=True)

        staging = self.incoming_directory / ".staging-generation-000001"
        staging.mkdir()
        (staging / "partial.dat").write_bytes(b"incomplete")

        results = import_incoming_snapshots(
            self.incoming_directory,
            self.replication_directory,
            self.world_id,
        )

        self.assertEqual(results, [])

if __name__ == "__main__":
    unittest.main()
