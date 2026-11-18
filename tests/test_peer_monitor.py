import json
import tempfile
from pathlib import Path

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcsync.peer_monitor import (
    PeerHealth,
    inspect_all_peers,
    inspect_peer,
)
from mcsync.peer_api import PeerAPIError
from mcsync.peers import Peer
from mcsync.secrets import SecretError


class PeerMonitorTests(unittest.TestCase):

    def setUp(self):
        self.peer = Peer("peer-b", "100.64.0.2")

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_running_peer(self, request):
        request.return_value = {
            "peer_id": "peer-b",
            "world_id": "MCSyncTest",
            "server": {"state": "RUNNING", "pid": 1234},
            "latest_verified_replica": {"generation": 8},
        }

        result = inspect_peer(
            self.peer, 8765, "a" * 32, "MCSyncTest"
        )

        self.assertTrue(result.reachable)
        self.assertEqual(result.server_state, "RUNNING")
        self.assertEqual(result.latest_generation, 8)
        self.assertIsNone(result.error)

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_stopped_peer(self, request):
        request.return_value = {
            "peer_id": "peer-b",
            "world_id": "MCSyncTest",
            "server": {"state": "STOPPED"},
            "latest_verified_replica": None,
        }

        result = inspect_peer(
            self.peer, 8765, "a" * 32, "MCSyncTest"
        )

        self.assertTrue(result.reachable)
        self.assertEqual(result.server_state, "STOPPED")

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_unreachable_peer_is_not_stopped(self, request):
        request.side_effect = PeerAPIError("Connection timed out")

        result = inspect_peer(
            self.peer, 8765, "a" * 32, "MCSyncTest"
        )

        self.assertFalse(result.reachable)
        self.assertIsNone(result.server_state)
        self.assertIn("timed out", result.error)

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_invalid_server_status(self, request):
        request.return_value = {
            "peer_id": "peer-b",
            "world_id": "MCSyncTest",
            "server": None,
        }

        result = inspect_peer(
            self.peer, 8765, "a" * 32, "MCSyncTest"
        )

        self.assertTrue(result.reachable)
        self.assertIsNone(result.server_state)
        self.assertIn("invalid server status", result.error)

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_invalid_server_state(self, request):
        request.return_value = {
            "peer_id": "peer-b",
            "world_id": "MCSyncTest",
            "server": {"state": None},
        }

        result = inspect_peer(
            self.peer, 8765, "a" * 32, "MCSyncTest"
        )

        self.assertTrue(result.reachable)
        self.assertIsNone(result.server_state)
        self.assertIn("invalid server state", result.error)

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_invalid_replica_generation_is_ignored(self, request):
        request.return_value = {
            "peer_id": "peer-b",
            "world_id": "MCSyncTest",
            "server": {"state": "STOPPED"},
            "latest_verified_replica": {"generation": "8"},
        }

        result = inspect_peer(
            self.peer, 8765, "a" * 32, "MCSyncTest"
        )

        self.assertTrue(result.reachable)
        self.assertIsNone(result.latest_generation)

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_registry_inspects_other_peers_only(self, request):
        peer_a = Peer("peer-a", "100.64.0.1")
        peer_b = Peer("peer-b", "100.64.0.2")
        peer_c = Peer("peer-c", "100.64.0.3")

        registry = SimpleNamespace(
            peers=(peer_a, peer_b, peer_c),
            communication_port=8765,
        )

        manager = Mock()
        manager.config = SimpleNamespace(
            peer_id="peer-a",
            world_id="MCSyncTest",
            peer_registry=registry,
        )

        request.return_value = {
            "peer_id": "peer-b",
            "world_id": "MCSyncTest",
            "server": {"state": "STOPPED"},
            "latest_verified_replica": None,
        }

        results = inspect_all_peers(manager, "a" * 32)

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [result.peer_id for result in results],
            ["peer-b", "peer-c"],
        )
        self.assertEqual(request.call_count, 2)

    @patch("mcsync.peer_monitor.request_peer_status")
    def test_inspect_all_peers_loads_token_from_secrets_file(self, request):
        with tempfile.TemporaryDirectory() as temp:
            secrets_file = Path(temp) / "secrets.json"
            token = "a" * 64

            secrets_file.write_text(
                json.dumps({"peer_api_token": token}),
                encoding="utf-8",
            )

            peer_b = Peer("peer-b", "100.64.0.2")
            peer_c = Peer("peer-c", "100.64.0.3")

            manager = Mock()
            manager.config = SimpleNamespace(
                peer_id="peer-a",
                world_id="MCSyncTest",
                peer_registry=SimpleNamespace(
                    peers=(
                        Peer("peer-a", "100.64.0.1"),
                        peer_b,
                        peer_c,
                    ),
                    communication_port=8765,
                ),
                secrets_file=secrets_file,
            )

            request.return_value = {
                "peer_id": "peer-b",
                "world_id": "MCSyncTest",
                "server": {"state": "STOPPED"},
                "latest_verified_replica": None,
            }

            results = inspect_all_peers(manager)

            self.assertEqual(len(results), 2)
            self.assertEqual(request.call_count, 2)

            for call in request.call_args_list:
                self.assertEqual(
                    call.kwargs["auth_token"],
                    token,
                )

    def test_inspect_all_peers_rejects_missing_secrets_file(self):
        manager = Mock()
        manager.config = SimpleNamespace(
            peer_id="peer-a",
            world_id="MCSyncTest",
            peer_registry=SimpleNamespace(
                peers=(Peer("peer-b", "100.64.0.2"),),
                communication_port=8765,
            ),
            secrets_file=(
                Path(tempfile.gettempdir())
                / "mcsync-monitor-missing-secrets.json"
            ),
        )

        with self.assertRaisesRegex(
            SecretError,
            "Secrets file does not exist",
        ):
            inspect_all_peers(manager)

    def test_missing_registry_is_rejected(self):
        manager = Mock()
        manager.config = SimpleNamespace(
            peer_id="peer-a",
            world_id="MCSyncTest",
            peer_registry=None,
        )

        with self.assertRaisesRegex(ValueError, "peer registry"):
            inspect_all_peers(manager, "a" * 32)


if __name__ == "__main__":
    unittest.main()
