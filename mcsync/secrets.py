
"""Local secret loading for MCSync."""

from __future__ import annotations

import json
from pathlib import Path


class SecretError(RuntimeError):
    """Raised when local MCSync secrets are invalid or unavailable."""


def load_peer_token(secrets_file: Path) -> str:
    """Load and validate the shared peer API token."""

    secrets_file = Path(secrets_file)

    if not secrets_file.exists():
        raise SecretError(
            f"Secrets file does not exist: {secrets_file}"
        )

    if not secrets_file.is_file():
        raise SecretError("Secrets path must be a regular file")

    try:
        data = json.loads(secrets_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecretError("Could not read secrets file") from exc

    if not isinstance(data, dict):
        raise SecretError("Secrets file must contain a JSON object")

    token = data.get("peer_api_token")

    if not isinstance(token, str):
        raise SecretError("peer_api_token must be a string")

    token = token.strip()

    if len(token) < 32:
        raise SecretError("Peer API token must contain at least 32 characters")

    return token
