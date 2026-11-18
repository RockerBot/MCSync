
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcsync.peer_status import build_peer_status


class PeerStatusTests(unittest.TestCase):

    def make_manager(self):
        config = SimpleNamespace(
            peer_id="peer-a",
            world_id="MCSyncTest",
            peer_registry=SimpleNamespace(protocol_version=1),
            replication_directory="replication",
            minecraft_version="1.21.1",
            loader="NeoForge",
            loader_version="21.1.252",
        )

        manager = Mock()
        manager.config = config
        manager.status.return_value = {
            "state": "STOPPED",
            "pid": None,
        }
        manager.ownership_lock.is_held = False

        return manager

    @patch("mcsync.peer_status.get_latest_verified_replica")
    def test_stopped_peer_status(self, get_replica):
        get_replica.return_value = None
        manager = self.make_manager()

        status = build_peer_status(manager)

        self.assertEqual(status["peer_id"], "peer-a")
        self.assertEqual(status["world_id"], "MCSyncTest")
        self.assertEqual(status["protocol_version"], 1)
        self.assertEqual(status["server"]["state"], "STOPPED")
        self.assertIsNone(status["latest_verified_replica"])
        self.assertFalse(status["ownership_lock_held"])

    @patch("mcsync.peer_status.get_latest_verified_replica")
    def test_running_peer_status(self, get_replica):
        get_replica.return_value = None
        manager = self.make_manager()

        manager.status.return_value = {
            "state": "RUNNING",
            "pid": 12345,
            "started_at": "2026-11-18T12:00:00+00:00",
            "log_file": "private/path/server.log",
        }
        manager.ownership_lock.is_held = True

        status = build_peer_status(manager)

        self.assertEqual(status["server"]["state"], "RUNNING")
        self.assertEqual(status["server"]["pid"], 12345)
        self.assertTrue(status["ownership_lock_held"])

        # Local filesystem paths must never be exposed.
        self.assertNotIn("log_file", status["server"])

    @patch("mcsync.peer_status.get_latest_verified_replica")
    def test_latest_verified_replica_is_reported(self, get_replica):
        manager = self.make_manager()

        get_replica.return_value = {
            "generation": 5,
            "path": "private/path",
            "metadata": {
                "manifest_sha256": "abc123",
                "created_at_utc": "2026-11-18T12:00:00+00:00",
                "created_by": "peer-a",
                "clean_shutdown": True,
                "file_count": 51,
            },
        }

        status = build_peer_status(manager)
        replica = status["latest_verified_replica"]

        self.assertEqual(replica["generation"], 5)
        self.assertEqual(replica["manifest_sha256"], "abc123")
        self.assertEqual(replica["file_count"], 51)
        self.assertNotIn("path", replica)

    @patch("mcsync.peer_status.get_latest_verified_replica")
    def test_replica_lookup_uses_expected_world_id(self, get_replica):
        get_replica.return_value = None
        manager = self.make_manager()

        build_peer_status(manager)

        get_replica.assert_called_once_with(
            "replication",
            expected_world_id="MCSyncTest",
        )


if __name__ == "__main__":
    unittest.main()
