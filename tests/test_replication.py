
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


if __name__ == "__main__":
    unittest.main()
