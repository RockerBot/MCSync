
import tempfile
import unittest

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from mcsync.config import MCSyncConfig
from mcsync.ownership import OwnershipError
from mcsync.server import ManagedServer, ServerError, ServerManager


class ServerTests(unittest.TestCase):

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.config = MCSyncConfig.from_file(
            root / "config" / "local.json"
        )

    def test_status_of_running_process(self):
        process = MagicMock()
        process.pid = 1234
        process.poll.return_value = None

        log_file = MagicMock()
        log_file.closed = False

        server = ManagedServer(
            process,
            log_file,
            Path("test.log"),
        )

        self.assertTrue(server.is_running)
        self.assertEqual(server.pid, 1234)

    def test_status_of_stopped_process(self):
        process = MagicMock()
        process.pid = 1234
        process.poll.return_value = 0
        process.stdin = MagicMock()
        process.stdin.closed = False

        log_file = MagicMock()
        log_file.closed = False

        server = ManagedServer(
            process,
            log_file,
            Path("test.log"),
        )

        self.assertFalse(server.is_running)

    def test_reject_multiline_command(self):
        process = MagicMock()
        process.pid = 1234
        process.poll.return_value = None

        server = ManagedServer(
            process,
            MagicMock(),
            Path("test.log"),
        )

        with self.assertRaises(ValueError):
            server.send_command("stop\nsay hello")

    def test_stop_sends_command_and_waits(self):
        process = MagicMock()
        process.pid = 1234
        process.poll.side_effect = [None, None, 0]
        process.returncode = 0
        process.stdin = MagicMock()
        process.stdin.closed = False

        log_file = MagicMock()
        log_file.closed = False

        server = ManagedServer(
            process,
            log_file,
            Path("test.log"),
        )

        server.stop(timeout=10)

        process.stdin.write.assert_called_once_with("stop\n")
        process.stdin.flush.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)

    def test_timeout_does_not_kill_server(self):
        from subprocess import TimeoutExpired

        process = MagicMock()
        process.pid = 1234
        process.poll.return_value = None
        process.stdin = MagicMock()
        process.stdin.closed = False
        process.wait.side_effect = TimeoutExpired("minecraft", 5)

        log_file = MagicMock()
        log_file.closed = False

        server = ManagedServer(
            process,
            log_file,
            Path("test.log"),
        )

        with self.assertRaises(ServerError):
            server.stop(timeout=5)

        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_second_manager_cannot_start_same_server(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)

            first_config = replace(
                self.config,
                runtime_directory=runtime,
            )
            second_config = replace(
                self.config,
                runtime_directory=runtime,
            )

            first = ServerManager(first_config)
            second = ServerManager(second_config)

            first.ownership_lock.acquire()

            try:
                with self.assertRaises(OwnershipError):
                    second.start()
            finally:
                first.ownership_lock.release()

    def test_separate_servers_can_own_separate_locks(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)

            first_config = replace(
                self.config,
                world_id="WorldA",
                runtime_directory=runtime,
            )
            second_config = replace(
                self.config,
                world_id="WorldB",
                runtime_directory=runtime,
            )

            first = ServerManager(first_config)
            second = ServerManager(second_config)

            first.ownership_lock.acquire()

            try:
                second.ownership_lock.acquire()
                self.assertTrue(second.ownership_lock.is_held)
            finally:
                second.ownership_lock.release()
                first.ownership_lock.release()

    def test_stop_releases_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ServerManager(
                replace(
                    self.config,
                    runtime_directory=Path(temp),
                )
            )

            manager.ownership_lock.acquire()

            process = MagicMock()
            process.poll.side_effect = [None, None, 0, 0]
            process.wait.return_value = 0
            process.returncode = 0
            process.stdin.closed = False

            log_file = MagicMock()
            log_file.closed = False

            manager.server = ManagedServer(
                process=process,
                log_file=log_file,
                log_path=Path(temp) / "server.log",
            )

            manager.stop()

            self.assertFalse(manager.ownership_lock.is_held)


if __name__ == "__main__":
    unittest.main()
