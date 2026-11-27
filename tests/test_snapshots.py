
import tempfile
import unittest

from dataclasses import replace
from pathlib import Path

import json

from mcsync.config import MCSyncConfig
from mcsync.snapshots import (
    SnapshotError,
    create_snapshot,
    verify_snapshot,
    list_snapshots,
    get_latest_snapshot,
    get_retention_report,
)


ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)

        original = MCSyncConfig.from_file(
            ROOT / "config" / "local.json"
        )

        server = base / "server"
        world = server / "MCSyncTest"
        world.mkdir(parents=True)

        (world / "level.dat").write_bytes(b"test-world-data")

        region = world / "region"
        region.mkdir()
        (region / "r.0.0.mca").write_bytes(b"test-region-data")

        self.config = replace(
            original,
            server_directory=server,
            world_directory=world,
            snapshots_directory=base / "snapshots",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_refuses_snapshot_without_clean_shutdown(self):
        with self.assertRaises(SnapshotError):
            create_snapshot(
                self.config,
                created_by="test-peer",
                clean_shutdown=False,
            )

    def test_create_and_verify_snapshot(self):
        snapshot = create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        self.assertEqual(snapshot.name, "generation-000001")

        metadata = verify_snapshot(
            snapshot,
            expected_world_id="MCSyncTest",
        )
        print('Outer test metadata: ', json.dumps(metadata, indent=2))

        self.assertEqual(metadata["generation"], 1)
        self.assertIsNone(metadata["parent_generation"])
        self.assertEqual(metadata["file_count"], 2)
        self.assertTrue(metadata["clean_shutdown"])

    def test_next_generation_uses_previous_as_parent(self):
        first = create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        second = create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        first_metadata = verify_snapshot(first)
        second_metadata = verify_snapshot(second)

        self.assertEqual(first_metadata["generation"], 1)
        self.assertEqual(second_metadata["generation"], 2)
        self.assertEqual(second_metadata["parent_generation"], 1)

    def test_detects_modified_snapshot_file(self):
        snapshot = create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        world_file = (
            snapshot / "world" / "MCSyncTest" / "level.dat"
        )
        world_file.write_bytes(b"modified-data")

        with self.assertRaises(SnapshotError):
            verify_snapshot(snapshot)

    def test_does_not_overwrite_existing_generation(self):
        first = create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        original_bytes = (
            first / "world" / "MCSyncTest" / "level.dat"
        ).read_bytes()

        second = create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        self.assertEqual(second.name, "generation-000002")
        self.assertEqual(
            (first / "world" / "MCSyncTest" / "level.dat").read_bytes(),
            original_bytes,
        )
    

    def test_list_snapshots(self):
        create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )
        create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        snapshots = list_snapshots(
            self.config.snapshots_directory,
            expected_world_id="MCSyncTest",
        )

        self.assertEqual(
            [item["generation"] for item in snapshots],
            [1, 2],
        )

    def test_get_latest_snapshot(self):
        create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )
        create_snapshot(
            self.config,
            created_by="test-peer",
            clean_shutdown=True,
        )

        latest = get_latest_snapshot(
            self.config.snapshots_directory,
            "MCSyncTest",
        )

        self.assertEqual(latest["generation"], 2)

    def test_retention_keeps_two_generations(self):
        for _ in range(4):
            create_snapshot(
                self.config,
                created_by="test-peer",
                clean_shutdown=True,
            )

        report = get_retention_report(
            self.config.snapshots_directory,
            keep=2,
            expected_world_id="MCSyncTest",
        )

        self.assertEqual(report["retained"], [3, 4])
        self.assertEqual(report["prune_candidates"], [1, 2])
        self.assertFalse(report["deletion_performed"])

    def test_retention_never_allows_less_than_two(self):
        with self.assertRaises(ValueError):
            get_retention_report(
                self.config.snapshots_directory,
                keep=1,
            )



if __name__ == "__main__":
    unittest.main()
