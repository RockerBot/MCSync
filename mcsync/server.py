
"""Minecraft server process management for MCSync."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import hashlib

from mcsync.ownership import OwnershipLock
from mcsync.config import MCSyncConfig


def log_call(f):
    def inner(*args, **kwargs):
        out = f(*args, **kwargs)
        print('Called', f.__qualname__, '->', out)
        return out
    return inner

class ServerError(RuntimeError):
    """Raised when a server operation cannot be completed."""


class ManagedServer:
    """Represents a Minecraft process started by MCSync."""

    def __init__(
        self,
        process: subprocess.Popen,
        log_file,
        log_path: Path,
    ):
        self.process = process
        self.log_file = log_file
        self.log_path = log_path
        self.started_at = datetime.now(timezone.utc)
        self._resources_closed = False

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def is_running(self) -> bool:
        running = self.process.poll() is None

        if not running:
            self._close_resources()

        return running

    @property
    def return_code(self) -> int | None:
        return self.process.poll()

    def _close_resources(self) -> None:
        if self._resources_closed:
            return

        self._resources_closed = True

        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()

        if not self.log_file.closed:
            self.log_file.close()

    def send_command(self, command: str) -> None:
        """Send a command to the Minecraft console."""

        if not command or "\n" in command or "\r" in command:
            raise ValueError("Command must be a single non-empty line")

        if not self.is_running:
            raise ServerError("Minecraft server is not running")

        if self.process.stdin is None:
            raise ServerError("Minecraft console input is unavailable")

        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise ServerError(
                f"Could not send Minecraft command: {exc}"
            ) from exc

    def stop(self, timeout: float = 120) -> None:
        """Request graceful shutdown and wait for process exit.

        Never force-kills the server if the timeout expires.
        """

        if not self.is_running:
            self._close_resources()
            return

        self.send_command("stop")
        # self.send_command(".")  # Hack to bypass the automatically inserted "pause" command from the neoforge installer.

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ServerError(
                f"Minecraft did not exit within {timeout} seconds. "
                "It has NOT been force-killed. Check the server log."
            )

        finally:
            if self.process.poll() is not None:
                self._close_resources()

        if self.process.returncode != 0:
            raise ServerError(
                f"Minecraft exited with code {self.process.returncode}. "
                f"Check log: {self.log_path}"
            )


class ServerManager:
    """Starts and manages one locally owned Minecraft process."""

    def __init__(self, config: MCSyncConfig):
        self.config = config
        self.server: ManagedServer | None = None
        self._retain_ownership = False

        # Hash the world ID to produce a filesystem-safe, server-specific name.
        world_hash = hashlib.sha256(
            config.world_id.encode("utf-8")
        ).hexdigest()[:16]

        lock_path = (
            config.runtime_directory
            / f"ownership-{world_hash}.lock"
        )

        self.ownership_lock = OwnershipLock(lock_path)

    @log_call
    def status(self) -> dict:
        """Return the status of the process owned by this manager."""

        if self.server is None:
            return {
                "state": "STOPPED",
                "pid": None,
            }

        if not self.server.is_running:
            if (
                self.ownership_lock.is_held
                and not self._retain_ownership
            ):
                self.ownership_lock.release()

            return {
                "state": "STOPPED",
                "pid": self.server.pid,
                "return_code": self.server.return_code,
            }

        return {
            "state": "RUNNING",
            "pid": self.server.pid,
            "started_at": self.server.started_at.isoformat(),
            "log_file": str(self.server.log_path),
        }

    def _build_environment(self) -> dict[str, str]:
        """Ensure the configured Java installation is used."""

        env = os.environ.copy()

        java_directory = str(self.config.java_executable.parent)
        java_home = str(self.config.java_executable.parent.parent)

        env["JAVA_HOME"] = java_home
        env["PATH"] = (
            java_directory
            + os.pathsep
            + env.get("PATH", "")
        )

        return env

    def _build_command(self) -> list[str]:
        """Build a platform-specific launch command."""

        configured = list(self.config.server_start_command)
        executable = configured[0]

        script = Path(executable)

        if not script.is_absolute():
            script = self.config.server_directory / script

        if sys.platform == "win32":
            if script.suffix.lower() in (".bat", ".cmd"):
                if not script.is_file():
                    raise ServerError(
                        f"Server startup script not found: {script}"
                    )

                return [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    "call",
                    str(script),
                    *configured[1:],
                ]

        if script.suffix.lower() == ".sh":
            if not script.is_file():
                raise ServerError(
                    f"Server startup script not found: {script}"
                )

            return ["bash", str(script), *configured[1:]]

        # Direct executable command
        if not script.is_absolute():
            return configured

        return [str(script), *configured[1:]]

    @log_call
    def start(self) -> ManagedServer:
        """Start Minecraft while holding exclusive local ownership."""

        if self.server is not None and self.server.is_running:
            raise ServerError("MCSync already owns a running server")

        self.config.validate()

        if not self.config.java_executable.is_file():
            raise ServerError("Configured Java executable is missing")

        # Reuse a lock retained across a checkpoint, if present.
        acquired_here = False

        if not self.ownership_lock.is_held:
            self.ownership_lock.acquire()
            acquired_here = True

        try:
            command = self._build_command()

            log_directory = (
                self.config.server_directory / "mcsync-logs"
            )
            log_directory.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now(timezone.utc).strftime(
                "%Y%m%d-%H%M%S"
            )

            log_path = log_directory / f"server-{timestamp}.log"
            log_file = log_path.open("ab")

            try:
                process = subprocess.Popen(
                    command,
                    cwd=self.config.server_directory,
                    env=self._build_environment(),
                    stdin=subprocess.PIPE,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    shell=False,
                )

            except Exception:
                log_file.close()
                raise

            self.server = ManagedServer(
                process=process,
                log_file=log_file,
                log_path=log_path,
            )

            self._retain_ownership = False
            return self.server

        except Exception:
            if acquired_here:
                self.ownership_lock.release()
            raise

    def send_command(self, command: str) -> None:
        if self.server is None:
            raise ServerError("MCSync has not started a server")

        self.server.send_command(command)

    @log_call
    def stop(
        self,
        timeout: float = 120,
        release_ownership: bool = True,
    ) -> None:
        """Stop Minecraft, optionally retaining ownership afterwards."""

        if self.server is None:
            raise ServerError("MCSync has not started a server")

        self._retain_ownership = not release_ownership

        try:
            self.server.stop(timeout=timeout)

        finally:
            if (
                release_ownership
                and self.ownership_lock.is_held
                and not self.server.is_running
            ):
                self.ownership_lock.release()
                self._retain_ownership = False

    def release_ownership(self) -> None:
        """Release ownership after Minecraft has stopped."""

        if self.server is not None and self.server.is_running:
            raise ServerError(
                "Cannot release ownership while Minecraft is running"
            )

        self.ownership_lock.release()
        self._retain_ownership = False
