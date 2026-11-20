
"""Authenticated local control API for the persistent MCSync manager."""

from __future__ import annotations

import errno
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcsync.secrets import load_local_control_token


class ControlAPIError(RuntimeError):
    """Raised when local manager communication fails."""

class LocalManagerUnavailable(ControlAPIError):
    """Raised when no local MCSync manager is listening."""

class LocalControlServer:
    """Local-only authenticated interface to the host manager."""

    def __init__(
        self,
        manager,
        secrets_file,
        on_stop_requested,
        host: str = "127.0.0.1",
        port: int = 8766,
    ):
        if host != "127.0.0.1":
            raise ValueError("Local control API must bind to 127.0.0.1")

        if not 0 <= port <= 65535:
            raise ValueError("Invalid local control API port")

        self.manager = manager
        self.on_stop_requested = on_stop_requested
        self._token = load_local_control_token(secrets_file)
        self._thread: threading.Thread | None = None

        manager_ref = manager
        token_ref = self._token
        stop_callback = on_stop_requested

        class Handler(BaseHTTPRequestHandler):

            def _send_json(self, status_code: int, payload: dict):
                body = json.dumps(payload).encode("utf-8")

                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _authenticated(self) -> bool:
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {token_ref}"

                if not hmac.compare_digest(supplied, expected):
                    self._send_json(
                        401,
                        {"error": "Authentication required"},
                    )
                    return False

                return True

            def do_GET(self):
                if self.path != "/v1/status":
                    self._send_json(404, {"error": "Not found"})
                    return

                if not self._authenticated():
                    return

                try:
                    self._send_json(200, manager_ref.status())
                except Exception:
                    self._send_json(
                        500,
                        {"error": "Could not produce manager status"},
                    )

            def do_POST(self):
                if not self._authenticated():
                    return

                if self.path == "/v1/save":
                    try:
                        manager_ref.send_command("save-all flush")
                        self._send_json(
                            200,
                            {"result": "Save command sent"},
                        )
                    except Exception:
                        self._send_json(
                            409,
                            {"error": "Could not send save command"},
                        )
                    return

                if self.path == "/v1/stop":
                    try:
                        stop_callback()
                        self._send_json(
                            202,
                            {"result": "Graceful shutdown requested"},
                        )
                    except Exception:
                        self._send_json(
                            500,
                            {"error": "Could not request shutdown"},
                        )
                    return

                self._send_json(404, {"error": "Not found"})

            def log_message(self, format, *args):
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server((host, port), Handler)
        self.host = host
        self.port = self._server.server_address[1]

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            raise ControlAPIError("Local control server is already running")

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="mcsync-local-control",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if self._thread is not None and self._thread.is_alive():
            self._server.shutdown()
            self._thread.join(timeout=5)

            if self._thread.is_alive():
                raise ControlAPIError("Local control server did not stop")

        self._server.server_close()


def request_local_control(
    port: int,
    token: str,
    action: str,
    timeout: float = 5,
) -> dict:
    """Send an authenticated command to the local host manager."""

    endpoints = {
        "status": ("GET", "/v1/status"),
        "save": ("POST", "/v1/save"),
        "stop": ("POST", "/v1/stop"),
    }

    if action not in endpoints:
        raise ValueError(f"Unsupported control action: {action}")

    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("Invalid local control token")

    if not 1 <= port <= 65535:
        raise ValueError("Invalid local control port")

    if timeout <= 0:
        raise ValueError("Timeout must be positive")

    method, path = endpoints[action]

    request = Request(
        f"http://127.0.0.1:{port}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        if exc.code == 401:
            raise ControlAPIError(
                "Local manager authentication failed"
            ) from exc

        raise ControlAPIError(
            f"Local manager returned HTTP {exc.code}"
        ) from exc

    except URLError as exc:
        reason = exc.reason

        if (
            isinstance(reason, OSError)
            and reason.errno == errno.ECONNREFUSED
        ):
            raise LocalManagerUnavailable(
                "No MCSync manager is listening"
            ) from exc

        raise ControlAPIError(
            f"Could not contact local manager: {exc}"
        ) from exc

    except (TimeoutError, OSError) as exc:
        raise ControlAPIError(
            f"Could not contact local manager: {exc}"
        ) from exc

    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlAPIError(
            "Local manager returned invalid JSON"
        ) from exc

    if not isinstance(data, dict):
        raise ControlAPIError(
            "Local manager response must be a JSON object"
        )

    return data
