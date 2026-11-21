
"""Persistent local host manager for MCSync."""

from __future__ import annotations

import threading
import time

from mcsync.server import ServerManager, ServerError
from mcsync.control_api import LocalControlServer
from mcsync.peer_api import PeerStatusServer


class HostManagerError(RuntimeError):
    """Raised when the persistent host manager cannot operate."""


class HostManager:
    """Keeps Minecraft and its ownership lock managed by one process."""

    def __init__(self, manager: ServerManager):
        self.manager = manager
        self.control_port = manager.config.control_port
        self.stop_requested = threading.Event()

        self.control_server: LocalControlServer | None = None
        self.peer_server: PeerStatusServer | None = None

    def request_stop(self) -> None:
        """Request graceful Minecraft shutdown."""

        self.stop_requested.set()

    def _start_apis(self) -> None:
        """Start local control and remote peer status APIs safely."""

        self.control_server = LocalControlServer(
            manager=self.manager,
            secrets_file=self.manager.config.secrets_file,
            on_stop_requested=self.request_stop,
            port=self.control_port,
        )

        self.peer_server = PeerStatusServer(self.manager)

        try:
            self.control_server.start()
            self.peer_server.start()

        except Exception as exc:
            # Clean up both services, including a partially started service.
            for server in (self.peer_server, self.control_server):
                if server is None:
                    continue

                try:
                    server.stop()
                except Exception:
                    pass

            self.control_server = None
            self.peer_server = None

            raise HostManagerError(
                f"Could not start manager APIs: {exc}"
            ) from exc

    def _stop_apis(self) -> None:
        """Stop API services."""

        errors = []

        for server in (self.peer_server, self.control_server):
            if server is None:
                continue

            try:
                server.stop()
            except Exception as exc:
                errors.append(str(exc))

        if errors:
            raise HostManagerError(
                "Could not stop all API services: " + "; ".join(errors)
            )

    def _ensure_server_stopped(self, server) -> None:
        """Keep managing Minecraft until it has actually exited."""

        while server.is_running:
            try:
                requested = self.stop_requested.wait(timeout=1)
            except KeyboardInterrupt:
                self.request_stop()
                requested = True

            if not requested:
                continue

            print("Graceful Minecraft shutdown requested...")

            try:
                self.manager.stop(timeout=120)

            except Exception as exc:
                if server.is_running:
                    print(f"Shutdown did not complete: {exc}")
                    print(
                        "Minecraft is still running. "
                        "Ownership is retained. "
                        "You can request shutdown again."
                    )
                    self.stop_requested.clear()
                    continue

            if server.is_running:
                print(
                    "Minecraft is still running. "
                    "Waiting for another shutdown request."
                )
                self.stop_requested.clear()

        # ServerManager.status() detects the exited process and releases
        # the ownership lock when it is no longer needed.
        try:
            self.manager.status()
        except Exception as exc:
            print(f"Warning: Could not refresh final server status: {exc}")

    def run(self) -> None:
        """Run the persistent manager until Minecraft stops."""

        server = None

        try:
            self._start_apis()

            print("MCSync APIs started.")
            print(
                f"Local control API: "
                f"http://127.0.0.1:{self.control_port}"
            )
            print(f"Peer status API: {self.peer_server.address}")

            server = self.manager.start()

            print("MCSync host manager started.")
            print(f"Minecraft PID: {server.pid}")
            print(f"Minecraft log: {server.log_path}")
            print("Host manager is running. Press Ctrl+C to stop.")

            self._ensure_server_stopped(server)

            print("Minecraft stopped successfully.")

        finally:
            # Never abandon a Minecraft process that is still running.
            if server is not None and server.is_running:
                print(
                    "HostManager encountered an interruption while "
                    "Minecraft was running. Continuing to manage it."
                )
                self._ensure_server_stopped(server)

            self._stop_apis()
            print("MCSync host manager stopped.")
