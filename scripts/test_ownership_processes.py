
"""Test MCSync ownership locks across independent processes."""

import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_child(lock_path, action):
    """Run a separate Python process to acquire or test a lock."""

    code = """
import sys
import time
from pathlib import Path
from mcsync.ownership import OwnershipLock, OwnershipError

lock = OwnershipLock(Path(sys.argv[1]))

try:
    lock.acquire()
    print("ACQUIRED", flush=True)

    if sys.argv[2] == "hold":
        time.sleep(float(sys.argv[3]))

    lock.release()

except OwnershipError:
    print("BLOCKED", flush=True)
    sys.exit(2)
"""

    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(lock_path),
            action,
            "30",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)

        lock_a = root / "server-a" / "ownership.lock"
        lock_b = root / "server-b" / "ownership.lock"

        print("TEST 1: Second process blocked by same-server lock")

        first = run_child(lock_a, "hold")

        try:
            output = first.stdout.readline().strip()
            if output != "ACQUIRED":
                raise RuntimeError(
                    f"First process failed to acquire lock: {output}"
                )

            second = run_child(lock_a, "once")
            stdout, stderr = second.communicate(timeout=10)

            if second.returncode != 2 or "BLOCKED" not in stdout:
                raise RuntimeError(
                    f"Second process was not blocked. "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )

            print("PASS: Second process was blocked.")

        finally:
            first.terminate()
            first.wait(timeout=10)

        print("\nTEST 2: Different servers can acquire independent locks")

        first = run_child(lock_a, "hold")

        try:
            if first.stdout.readline().strip() != "ACQUIRED":
                raise RuntimeError("First server failed to acquire lock")

            second = run_child(lock_b, "once")
            stdout, stderr = second.communicate(timeout=10)

            if second.returncode != 0 or "ACQUIRED" not in stdout:
                raise RuntimeError(
                    f"Independent server lock failed. "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )

            print("PASS: Separate server acquired its own lock.")

        finally:
            first.terminate()
            first.wait(timeout=10)

        print("\nTEST 3: Lock becomes available after process crash")

        first = run_child(lock_a, "hold")

        try:
            if first.stdout.readline().strip() != "ACQUIRED":
                raise RuntimeError("First process failed to acquire lock")

            # Simulate abrupt process termination.
            first.kill()
            first.wait(timeout=10)

            second = run_child(lock_a, "once")
            stdout, stderr = second.communicate(timeout=10)

            if second.returncode != 0 or "ACQUIRED" not in stdout:
                raise RuntimeError(
                    f"Lock was not released after process exit. "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )

            print("PASS: Lock recovered after process termination.")

        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=10)

    print("\nALL MULTI-PROCESS OWNERSHIP TESTS PASSED")


if __name__ == "__main__":
    main()
