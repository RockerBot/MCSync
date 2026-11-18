
"""Authenticated, read-only HTTP communication between MCSync peers."""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcsync.peers import Peer
from mcsync.secrets import load_peer_token


class PeerAPIError(RuntimeError):
    """Raised when peer communication fails or returns invalid data."""


class PeerStatusServer:
    """Authenticated HTTP server exposing read-only peer status."""

    def __init__(
        self,
        manager,
        auth_token: str | None = None,
        bind_host: str | None = None,
        port: int | None = None,
    ):
        registry = manager.config.peer_registry

        if registry is None:
            raise ValueError("A peer registry is required")

        # Load the token from the local secrets file when not supplied.
        if auth_token is None:
            secrets_file = manager.config.secrets_file

            if secrets_file is None:
                raise ValueError("A secrets file is required")

            auth_token = load_peer_token(secrets_file)

        if not isinstance(auth_token, str) or len(auth_token) < 32:
            raise ValueError(
                "Peer API token must contain at least 32 characters"
            )

        local_peer = registry.get_peer(manager.config.peer_id)

        self.bind_host = bind_host or local_peer.host
        self.port = port if port is not None else registry.communication_port

        if not 0 <= self.port <= 65535:
            raise ValueError("Invalid peer API port")

        self.manager = manager
        self._auth_token = auth_token
        self._thread: threading.Thread | None = None

        manager_ref = self.manager
        token_ref = self._auth_token

        class Handler(BaseHTTPRequestHandler):

            def _send_json(self, status_code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")

                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path != "/v1/status":
                    self._send_json(404, {"error": "Not found"})
                    return

                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {token_ref}"

                if not hmac.compare_digest(supplied, expected):
                    self._send_json(
                        401,
                        {"error": "Authentication required"},
                    )
                    return

                try:
                    from mcsync.peer_status import build_peer_status

                    status = build_peer_status(manager_ref)
                    self._send_json(200, status)
                except Exception:
                    # Do not expose local exception details to remote peers.
                    self._send_json(
                        500,
                        {"error": "Could not produce peer status"},
                    )

            def do_POST(self):
                self._send_json(405, {"error": "Method not allowed"})

            def do_PUT(self):
                self._send_json(405, {"error": "Method not allowed"})

            def do_DELETE(self):
                self._send_json(405, {"error": "Method not allowed"})

            def log_message(self, format, *args):
                # Avoid writing request details to standard error.
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server((self.bind_host, self.port), Handler)
        self.port = self._server.server_address[1]

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    def start(self) -> None:
        """Start the HTTP service in a background thread."""

        if self._thread is not None and self._thread.is_alive():
            raise PeerAPIError("Peer status server is already running")

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="mcsync-peer-status",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the HTTP service."""

        if self._thread is not None and self._thread.is_alive():
            self._server.shutdown()
            self._thread.join(timeout=5)

            if self._thread.is_alive():
                raise PeerAPIError("Peer status server did not stop")

        self._server.server_close()


def request_peer_status(
    peer: Peer,
    port: int,
    auth_token: str,
    expected_world_id: str,
    timeout: float = 5,
) -> dict:
    """Request and validate another peer's status."""

    if not isinstance(auth_token, str) or len(auth_token) < 32:
        raise ValueError("Peer API token must contain at least 32 characters")

    if not 1 <= port <= 65535:
        raise ValueError("Invalid peer API port")

    if timeout <= 0:
        raise ValueError("Timeout must be positive")

    url = f"http://{peer.host}:{port}/v1/status"

    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise PeerAPIError(
                    f"Peer returned HTTP {response.status}"
                )

            data = json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        if exc.code == 401:
            raise PeerAPIError("Peer authentication failed") from exc

        raise PeerAPIError(
            f"Peer returned HTTP {exc.code}"
        ) from exc

    except (URLError, TimeoutError, OSError) as exc:
        raise PeerAPIError(
            f"Could not contact {peer.peer_id}: {exc}"
        ) from exc

    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PeerAPIError("Peer returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise PeerAPIError("Peer response must be a JSON object")

    if data.get("protocol_version") != 1:
        raise PeerAPIError("Peer protocol version mismatch")

    if data.get("peer_id") != peer.peer_id:
        raise PeerAPIError("Peer identity mismatch")

    if data.get("world_id") != expected_world_id:
        raise PeerAPIError("Peer world ID mismatch")

    return data
