
import json
import tempfile
import unittest
from pathlib import Path

from mcsync.peers import PeerRegistry, PeerRegistryError


class PeerRegistryTests(unittest.TestCase):

    def write_registry(self, directory, data):
        path = Path(directory) / "peers.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def valid_data(self):
        return {
            "protocol_version": 1,
            "world_id": "MCSyncTest",
            "communication_port": 8765,
            "peers": [
                {"peer_id": "peer-a", "host": "127.0.0.1"},
                {"peer_id": "peer-b", "host": "peer-b"},
                {"peer_id": "peer-c", "host": "peer-c"},
            ],
        }

    def test_load_valid_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, self.valid_data())

            registry = PeerRegistry.from_file(path)

            self.assertEqual(registry.world_id, "MCSyncTest")
            self.assertEqual(registry.communication_port, 8765)
            self.assertEqual(len(registry.peers), 3)

    def test_get_peer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, self.valid_data())
            registry = PeerRegistry.from_file(path)

            peer = registry.get_peer("peer-b")

            self.assertEqual(peer.host, "peer-b")

    def test_peer_lookup_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, self.valid_data())
            registry = PeerRegistry.from_file(path)

            self.assertEqual(
                registry.get_peer("PEER-A").peer_id,
                "peer-a",
            )

    def test_unknown_peer_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, self.valid_data())
            registry = PeerRegistry.from_file(path)

            with self.assertRaises(PeerRegistryError):
                registry.get_peer("peer-z")

    def test_validate_local_peer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, self.valid_data())
            registry = PeerRegistry.from_file(path)

            peer = registry.validate_local_peer(
                "peer-a",
                "MCSyncTest",
            )

            self.assertEqual(peer.host, "127.0.0.1")

    def test_wrong_world_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, self.valid_data())
            registry = PeerRegistry.from_file(path)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "does not match",
            ):
                registry.validate_local_peer(
                    "peer-a",
                    "AnotherWorld",
                )

    def test_duplicate_peer_ids_are_rejected(self):
        data = self.valid_data()
        data["peers"].append(
            {"peer_id": "PEER-A", "host": "192.168.1.20"}
        )

        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, data)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "Duplicate peer_id",
            ):
                PeerRegistry.from_file(path)

    def test_duplicate_endpoints_are_rejected(self):
        data = self.valid_data()
        data["peers"][1]["host"] = "127.0.0.1"

        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, data)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "Duplicate peer endpoint",
            ):
                PeerRegistry.from_file(path)

    def test_invalid_port_is_rejected(self):
        data = self.valid_data()
        data["communication_port"] = 70000

        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, data)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "communication_port",
            ):
                PeerRegistry.from_file(path)

    def test_unsupported_protocol_is_rejected(self):
        data = self.valid_data()
        data["protocol_version"] = 2

        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, data)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "Unsupported",
            ):
                PeerRegistry.from_file(path)

    def test_invalid_hostname_is_rejected(self):
        data = self.valid_data()
        data["peers"][1]["host"] = "https://peer-b.example.com/path"

        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, data)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "Invalid peer host",
            ):
                PeerRegistry.from_file(path)

    def test_empty_peer_list_is_rejected(self):
        data = self.valid_data()
        data["peers"] = []

        with tempfile.TemporaryDirectory() as temp:
            path = self.write_registry(temp, data)

            with self.assertRaisesRegex(
                PeerRegistryError,
                "At least one peer",
            ):
                PeerRegistry.from_file(path)


if __name__ == "__main__":
    unittest.main()
