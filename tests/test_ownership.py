
import tempfile
import unittest
from pathlib import Path

from mcsync.ownership import OwnershipError, OwnershipLock


class OwnershipLockTests(unittest.TestCase):

    def test_acquire_and_release(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ownership.lock"
            lock = OwnershipLock(path)

            lock.acquire()
            self.assertTrue(lock.is_held)

            lock.release()
            self.assertFalse(lock.is_held)

            # A new lock can acquire the same file.
            second = OwnershipLock(path)
            second.acquire()
            self.assertTrue(second.is_held)
            second.release()

    def test_prevents_second_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ownership.lock"

            first = OwnershipLock(path)
            second = OwnershipLock(path)

            first.acquire()

            try:
                with self.assertRaises(OwnershipError):
                    second.acquire()
            finally:
                first.release()

            # The second manager can acquire it after release.
            second.acquire()
            self.assertTrue(second.is_held)
            second.release()

    def test_separate_servers_can_have_separate_locks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            first = OwnershipLock(root / "server-a" / "ownership.lock")
            second = OwnershipLock(root / "server-b" / "ownership.lock")

            first.acquire()
            second.acquire()

            self.assertTrue(first.is_held)
            self.assertTrue(second.is_held)

            second.release()
            first.release()

    def test_releasing_unheld_lock_is_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = OwnershipLock(Path(temp) / "ownership.lock")

            lock.release()
            self.assertFalse(lock.is_held)


if __name__ == "__main__":
    unittest.main()
