
"""Cross-platform OS-level ownership locks for MCSync."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO


class OwnershipError(RuntimeError):
    """Raised when ownership cannot be acquired or released."""


class OwnershipLock:
    """An exclusive lock for one local MCSync server instance."""

    def __init__(self, lock_path: Path):
        self.lock_path = Path(lock_path)
        self._file: TextIO | None = None

    @property
    def is_held(self) -> bool:
        return self._file is not None

    def acquire(self) -> None:
        """Acquire the lock without waiting."""

        if self.is_held:
            raise OwnershipError("This manager already holds the lock")

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            file = self.lock_path.open("a+", encoding="utf-8")

            # Ensure the lock file contains at least one byte.
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                file.write(" ")
                file.flush()

            file.seek(0)

            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    file.close()
                    raise OwnershipError(
                        f"Another MCSync manager owns this server: "
                        f"{self.lock_path}"
                    ) from exc

            else:
                import fcntl

                try:
                    fcntl.flock(
                        file.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                except OSError as exc:
                    file.close()
                    raise OwnershipError(
                        f"Another MCSync manager owns this server: "
                        f"{self.lock_path}"
                    ) from exc

            self._file = file

        except OwnershipError:
            raise
        except OSError as exc:
            raise OwnershipError(
                f"Could not acquire ownership lock: {exc}"
            ) from exc

    def release(self) -> None:
        """Release the lock."""

        if self._file is None:
            return

        file = self._file
        self._file = None

        try:
            file.seek(0)

            if os.name == "nt":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_UN)

        except OSError as exc:
            raise OwnershipError(
                f"Could not release ownership lock: {exc}"
            ) from exc

        finally:
            file.close()

    def __enter__(self) -> "OwnershipLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
