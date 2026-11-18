
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mcsync.checkpoint import (
    CheckpointError,
    _wait_for_save_confirmation,
    create_checkpoint,
)
from mcsync.ownership import OwnershipError, OwnershipLock


class CheckpointTests(unittest.TestCase):

    def test_wait_for_save_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "server.log"
            log.write_text("Starting server\n", encoding="utf-8")
            offset = log.stat().st_size

            log.write_text(
                "Starting server\nSaved the game\n",
                encoding="utf-8",
            )

            manager = Mock()
            manager.server.is_running = True

            _wait_for_save_confirmation(
                manager,
                log,
                offset,
                timeout=1,
            )

    def test_refuses_checkpoint_without_owned_server(self):
        manager = Mock()
        manager.server = None

        with self.assertRaises(CheckpointError):
            create_checkpoint(
                manager,
                created_by="test-peer",
            )

    @patch("mcsync.checkpoint.verify_snapshot", return_value=True)
    @patch("mcsync.checkpoint.create_snapshot")
    @patch("mcsync.checkpoint._wait_for_save_confirmation")
    @patch("mcsync.checkpoint.publish_snapshot")
    def test_checkpoint_stops_snapshots_and_restarts(
        self,
        publish_mock,
        wait_mock,
        snapshot_mock,
        verify_mock,
    ):
        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp) / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path

            snapshot_directory = Path("generation-000003")
            snapshot_mock.return_value = snapshot_directory
            replica_directory = Path("replication/generation-000003")
            publish_mock.return_value = replica_directory

            result = create_checkpoint(
                manager,
                created_by="test-peer",
                restart=True,
            )

            manager.send_command.assert_called_once_with("save-all flush")
            wait_mock.assert_called_once()
            manager.stop.assert_called_once_with(
                timeout=180,
                release_ownership=False,
            )
            snapshot_mock.assert_called_once()
            verify_mock.assert_called_once()
            manager.start.assert_called_once()

            self.assertEqual(result.generation, 3)
            self.assertTrue(result.restarted)
            publish_mock.assert_called_once_with(
                snapshot_directory,
                manager.config.replication_directory,
                expected_world_id=manager.config.world_id,
            )

            self.assertEqual(result.replica_directory, replica_directory)
            self.assertIsNone(result.replication_error)

    @patch("mcsync.checkpoint._wait_for_save_confirmation")
    def test_save_timeout_does_not_stop_server(self, wait_mock):
        wait_mock.side_effect = CheckpointError("Save timed out")

        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp) / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path

            with self.assertRaises(CheckpointError):
                create_checkpoint(
                    manager,
                    created_by="test-peer",
                )

            manager.stop.assert_not_called()
            manager.start.assert_not_called()

    def test_ownership_remains_locked_during_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock_path = root / "ownership.lock"
            owner = OwnershipLock(lock_path)
            owner.acquire()

            log_path = root / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path
            manager.ownership_lock = owner
            manager.start.return_value = None

            def inspect_lock(*args, **kwargs):
                contender = OwnershipLock(lock_path)
                with self.assertRaises(OwnershipError):
                    contender.acquire()
                return root / "generation-000001"

            try:
                with patch(
                    "mcsync.checkpoint._wait_for_save_confirmation"
                ), patch(
                    "mcsync.checkpoint.create_snapshot",
                    side_effect=inspect_lock,
                ), patch(
                    "mcsync.checkpoint.verify_snapshot",
                    return_value=True,
                ):
                    create_checkpoint(
                        manager,
                        created_by="test-peer",
                        restart=True,
                    )

                self.assertTrue(owner.is_held)
                manager.stop.assert_called_once_with(
                    timeout=180,
                    release_ownership=False,
                )
            finally:
                owner.release()

    def test_restart_disabled_releases_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = OwnershipLock(root / "ownership.lock")
            owner.acquire()

            log_path = root / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path
            manager.ownership_lock = owner
            manager.release_ownership.side_effect = owner.release

            try:
                with patch(
                    "mcsync.checkpoint._wait_for_save_confirmation"
                ), patch(
                    "mcsync.checkpoint.create_snapshot",
                    return_value=root / "generation-000001",
                ), patch(
                    "mcsync.checkpoint.verify_snapshot",
                    return_value=True,
                ):
                    result = create_checkpoint(
                        manager,
                        created_by="test-peer",
                        restart=False,
                    )

                self.assertFalse(owner.is_held)
                self.assertFalse(result.restarted)
                manager.start.assert_not_called()
                manager.release_ownership.assert_called_once()
            finally:
                owner.release()

    def test_snapshot_failure_and_restart_failure_retain_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = OwnershipLock(root / "ownership.lock")
            owner.acquire()

            log_path = root / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path
            manager.ownership_lock = owner
            manager.start.side_effect = RuntimeError("Startup failed")

            try:
                with patch(
                    "mcsync.checkpoint._wait_for_save_confirmation"
                ), patch(
                    "mcsync.checkpoint.create_snapshot",
                    side_effect=RuntimeError("Snapshot failed"),
                ):
                    with self.assertRaises(CheckpointError):
                        create_checkpoint(
                            manager,
                            created_by="test-peer",
                            restart=True,
                        )

                self.assertTrue(owner.is_held)
            finally:
                owner.release()

    def test_snapshot_failure_without_restart_releases_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = OwnershipLock(root / "ownership.lock")
            owner.acquire()

            log_path = root / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path
            manager.ownership_lock = owner
            manager.release_ownership.side_effect = owner.release

            try:
                with patch(
                    "mcsync.checkpoint._wait_for_save_confirmation"
                ), patch(
                    "mcsync.checkpoint.create_snapshot",
                    side_effect=RuntimeError("Snapshot failed"),
                ):
                    with self.assertRaises(CheckpointError):
                        create_checkpoint(
                            manager,
                            created_by="test-peer",
                            restart=False,
                        )

                self.assertFalse(owner.is_held)
            finally:
                owner.release()

    def test_replication_failure_does_not_prevent_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            log_path = root / "server.log"
            log_path.write_text("Server started\n", encoding="utf-8")

            snapshot_directory = root / "generation-000005"

            manager = Mock()
            manager.server.is_running = True
            manager.server.log_path = log_path

            with patch(
                "mcsync.checkpoint._wait_for_save_confirmation"
            ), patch(
                "mcsync.checkpoint.create_snapshot",
                return_value=snapshot_directory,
            ), patch(
                "mcsync.checkpoint.verify_snapshot",
                return_value=True,
            ), patch(
                "mcsync.checkpoint.publish_snapshot",
                side_effect=RuntimeError("Syncthing directory unavailable"),
            ) as publish_mock:

                result = create_checkpoint(
                    manager,
                    created_by="test-peer",
                    restart=True,
                )

            publish_mock.assert_called_once()

            self.assertEqual(result.generation, 5)
            self.assertIsNone(result.replica_directory)
            self.assertIn(
                "Syncthing directory unavailable",
                result.replication_error,
            )

            manager.stop.assert_called_once_with(
                timeout=180,
                release_ownership=False,
            )
            manager.start.assert_called_once()

if __name__ == "__main__":
    unittest.main()
