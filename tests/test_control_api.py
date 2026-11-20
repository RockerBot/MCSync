
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import socket

from mcsync.control_api import (
    ControlAPIError,
    LocalControlServer,
    request_local_control,
    LocalManagerUnavailable,
)


class ControlAPITests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.temp.name) / "secrets.json"
        self.token = "a" * 64

        self.secrets_file.write_text(
            json.dumps({"local_control_token": self.token}),
            encoding="utf-8",
        )

        self.manager = Mock()
        self.manager.status.return_value = {
            "state": "RUNNING",
            "pid": 1234,
        }

        self.stop_requested = Mock()

        self.server = LocalControlServer(
            manager=self.manager,
            secrets_file=self.secrets_file,
            on_stop_requested=self.stop_requested,
            port=0,
        )
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.temp.cleanup()

    def test_authenticated_status(self):
        result = request_local_control(
            self.server.port,
            self.token,
            "status",
        )

        self.assertEqual(result["state"], "RUNNING")
        self.assertEqual(result["pid"], 1234)

    def test_save_command(self):
        result = request_local_control(
            self.server.port,
            self.token,
            "save",
        )

        self.manager.send_command.assert_called_once_with(
            "save-all flush"
        )
        self.assertIn("result", result)

    def test_stop_request(self):
        result = request_local_control(
            self.server.port,
            self.token,
            "stop",
        )

        self.stop_requested.assert_called_once()
        self.assertIn("result", result)

    def test_wrong_token_rejected(self):
        with self.assertRaises(ControlAPIError):
            request_local_control(
                self.server.port,
                "b" * 64,
                "status",
            )

    def test_invalid_action_rejected(self):
        with self.assertRaises(ValueError):
            request_local_control(
                self.server.port,
                self.token,
                "restart",
            )

    def test_server_must_bind_to_localhost(self):
        with self.assertRaises(ValueError):
            LocalControlServer(
                manager=self.manager,
                secrets_file=self.secrets_file,
                on_stop_requested=self.stop_requested,
                host="0.0.0.0",
            )

    def test_connection_refused_reports_manager_unavailable(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            unused_port = sock.getsockname()[1]

        with self.assertRaises(LocalManagerUnavailable):
            request_local_control(
                unused_port,
                self.token,
                "status",
            )

if __name__ == "__main__":
    unittest.main()
