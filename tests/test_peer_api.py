
import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from mcsync.peer_api import (
    PeerAPIError,
    PeerStatusServer,
    request_peer_status,
)
from mcsync.peers import Peer
from mcsync.secrets import SecretError


TOKEN = "test-token-for-mcsync-peer-api-123456"


class PeerAPITests(unittest.TestCase):

    def setUp(self):
        self.manager = Mock()

        self.manager.config = SimpleNamespace(
            peer_id="peer-a",
            world_id="MCSyncTest",
            peer_registry=SimpleNamespace(
                communication_port=8765,
                protocol_version=1,
                get_peer=lambda peer_id: Peer(
                    peer_id="peer-a",
                    host="127.0.0.1",
                ),
            ),
            minecraft_version="1.21.1",
            loader="NeoForge",
            loader_version="21.1.252",
            replication_directory="replication",
        )

        self.manager.status.return_value = {
            "state": "STOPPED",
            "pid": None,
        }

        self.manager.ownership_lock.is_held = False

        self.server = PeerStatusServer(
            self.manager,
            TOKEN,
            bind_host="127.0.0.1",
            port=0,
        )
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_authenticated_status_request(self):
        peer = Peer("peer-a", "127.0.0.1")

        status = request_peer_status(
            peer,
            self.server.port,
            TOKEN,
            "MCSyncTest",
        )

        self.assertEqual(status["peer_id"], "peer-a")
        self.assertEqual(status["world_id"], "MCSyncTest")
        self.assertEqual(status["server"]["state"], "STOPPED")

    def test_missing_authentication_is_rejected(self):
        request = Request(
            f"http://127.0.0.1:{self.server.port}/v1/status"
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)

        self.assertEqual(context.exception.code, 401)

    def test_wrong_token_is_rejected(self):
        peer = Peer("peer-a", "127.0.0.1")

        with self.assertRaisesRegex(
            PeerAPIError,
            "authentication failed",
        ):
            request_peer_status(
                peer,
                self.server.port,
                "wrong-token-that-is-long-enough-123",
                "MCSyncTest",
            )

    def test_unknown_endpoint_returns_404(self):
        request = Request(
            f"http://127.0.0.1:{self.server.port}/unknown",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)

        self.assertEqual(context.exception.code, 404)

    def test_post_is_rejected(self):
        request = Request(
            f"http://127.0.0.1:{self.server.port}/v1/status",
            data=b"{}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)

        self.assertEqual(context.exception.code, 405)

    def test_wrong_world_id_is_rejected_by_client(self):
        peer = Peer("peer-a", "127.0.0.1")

        with self.assertRaisesRegex(
            PeerAPIError,
            "world ID mismatch",
        ):
            request_peer_status(
                peer,
                self.server.port,
                TOKEN,
                "DifferentWorld",
            )

    def test_invalid_token_is_rejected_before_server_creation(self):
        with self.assertRaises(ValueError):
            PeerStatusServer(
                self.manager,
                "short",
                bind_host="127.0.0.1",
                port=0,
            )

    def test_server_loads_token_from_secrets_file(self):
        with tempfile.TemporaryDirectory() as temp:
            secrets_file = Path(temp) / "secrets.json"
            secrets_file.write_text(
                json.dumps({"peer_api_token": TOKEN}),
                encoding="utf-8",
            )

            self.manager.config.secrets_file = secrets_file

            server = PeerStatusServer(
                self.manager,
                bind_host="127.0.0.1",
                port=0,
            )

            try:
                self.assertEqual(server._auth_token, TOKEN)
                self.assertNotEqual(server.port, 8765)
            finally:
                server.stop()

    def test_server_rejects_missing_secrets_file(self):
        self.manager.config.secrets_file = (
            Path(tempfile.gettempdir()) / "mcsync-missing-secrets.json"
        )

        with self.assertRaisesRegex(
            SecretError,
            "Secrets file does not exist",
        ):
            PeerStatusServer(
                self.manager,
                bind_host="127.0.0.1",
                port=0,
            )

if __name__ == "__main__":
    unittest.main()
