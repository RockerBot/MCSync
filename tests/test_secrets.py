
import json
import tempfile
import unittest
from pathlib import Path

from mcsync.secrets import SecretError, load_peer_token


class SecretTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.secrets_file = self.directory / "secrets.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_secrets(self, data):
        self.secrets_file.write_text(
            json.dumps(data),
            encoding="utf-8",
        )

    def test_load_valid_token(self):
        token = "a" * 64
        self.write_secrets({"peer_api_token": token})

        self.assertEqual(
            load_peer_token(self.secrets_file),
            token,
        )

    def test_missing_file(self):
        with self.assertRaisesRegex(SecretError, "does not exist"):
            load_peer_token(self.secrets_file)

    def test_short_token_rejected(self):
        self.write_secrets({"peer_api_token": "short"})

        with self.assertRaisesRegex(SecretError, "at least 32"):
            load_peer_token(self.secrets_file)

    def test_missing_token_rejected(self):
        self.write_secrets({})

        with self.assertRaisesRegex(SecretError, "must be a string"):
            load_peer_token(self.secrets_file)

    def test_non_string_token_rejected(self):
        self.write_secrets({"peer_api_token": 12345})

        with self.assertRaisesRegex(SecretError, "must be a string"):
            load_peer_token(self.secrets_file)

    def test_invalid_json_rejected(self):
        self.secrets_file.write_text(
            "{invalid json",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(SecretError, "Could not read"):
            load_peer_token(self.secrets_file)

    def test_json_array_rejected(self):
        self.secrets_file.write_text(
            "[]",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(SecretError, "JSON object"):
            load_peer_token(self.secrets_file)

    def test_directory_rejected(self):
        with self.assertRaisesRegex(SecretError, "regular file"):
            load_peer_token(self.directory)


if __name__ == "__main__":
    unittest.main()
