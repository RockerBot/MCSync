
import unittest
from unittest.mock import Mock, patch

from mcsync.host_manager import HostManager
from mcsync.server import ServerError


class HostManagerTests(unittest.TestCase):

    def setUp(self):
        self.manager = Mock()
        self.server = Mock()
        self.server.pid = 1234
        self.server.log_path = "server.log"
        self.server.is_running = True

        self.manager.start.return_value = self.server

        self.host = HostManager(self.manager)

    @patch("mcsync.host_manager.PeerStatusServer")
    @patch("mcsync.host_manager.LocalControlServer")
    def test_start_starts_minecraft_and_both_apis(
        self,
        mock_control,
        mock_peer,
    ):
        self.host._start_apis()

        self.manager.start.assert_not_called()
        mock_control.return_value.start.assert_called_once()
        mock_peer.return_value.start.assert_called_once()

    @patch("mcsync.host_manager.PeerStatusServer")
    @patch("mcsync.host_manager.LocalControlServer")
    def test_stop_request_sets_event(
        self,
        mock_control,
        mock_peer,
    ):
        self.host.request_stop()

        self.assertTrue(self.host.stop_requested.is_set())

    @patch("mcsync.host_manager.PeerStatusServer")
    @patch("mcsync.host_manager.LocalControlServer")
    def test_stop_apis_stops_both_services(
        self,
        mock_control,
        mock_peer,
    ):
        self.host._start_apis()
        self.host._stop_apis()

        mock_peer.return_value.stop.assert_called_once()
        mock_control.return_value.stop.assert_called_once()

    @patch("mcsync.host_manager.PeerStatusServer")
    @patch("mcsync.host_manager.LocalControlServer")
    def test_peer_api_failure_stops_control_api(
        self,
        mock_control,
        mock_peer,
    ):
        mock_peer.return_value.start.side_effect = RuntimeError(
            "Peer API failed"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Could not start manager APIs",
        ):
            self.host._start_apis()

        mock_control.return_value.start.assert_called_once()
        mock_control.return_value.stop.assert_called_once()
        mock_peer.return_value.stop.assert_called_once()

        self.assertIsNone(self.host.control_server)
        self.assertIsNone(self.host.peer_server)

    @patch("mcsync.host_manager.PeerStatusServer")
    @patch("mcsync.host_manager.LocalControlServer")
    def test_shutdown_timeout_does_not_force_kill(
        self,
        mock_control,
        mock_peer,
    ):
        self.manager.stop.side_effect = ServerError(
            "Minecraft did not exit"
        )

        self.assertTrue(self.server.is_running)

        with self.assertRaises(ServerError):
            self.manager.stop(timeout=120)

        self.assertTrue(self.server.is_running)

    def test_host_manager_uses_existing_server_manager(self):
        host = HostManager(self.manager)

        self.assertIs(host.manager, self.manager)

    def test_stop_event_is_initially_clear(self):
        self.assertFalse(self.host.stop_requested.is_set())

    @patch("mcsync.host_manager.HostManager._start_apis")
    @patch("mcsync.host_manager.HostManager._stop_apis")
    def test_unexpected_server_exit_refreshes_status(
        self,
        mock_stop_apis,
        mock_start_apis,
    ):
        self.server.is_running = False
        self.host._ensure_server_stopped(self.server)
        self.manager.status.assert_called_once()

    def test_ensure_server_stopped_waits_for_shutdown_request(self):
        self.server.is_running = True

        self.host.stop_requested.wait = Mock(
            side_effect=[False, False, True]
        )

        def stop_server(timeout):
            self.server.is_running = False

        self.manager.stop.side_effect = stop_server
        self.host._ensure_server_stopped(self.server)

        self.manager.stop.assert_called_once_with(timeout=120)
        self.manager.status.assert_called_once()
        self.assertFalse(self.server.is_running)

    def test_shutdown_failure_keeps_manager_waiting(self):
        self.server.is_running = True

        self.host.stop_requested.wait = Mock(
            side_effect=[True, True]
        )

        def stop_server(timeout):
            if self.manager.stop.call_count == 1:
                raise ServerError("Minecraft did not exit")

            self.server.is_running = False

        self.manager.stop.side_effect = stop_server
        self.host._ensure_server_stopped(self.server)

        self.assertEqual(self.manager.stop.call_count, 2)
        self.assertFalse(self.server.is_running)
        self.manager.status.assert_called_once()

    @patch("mcsync.host_manager.HostManager._start_apis")
    @patch("mcsync.host_manager.HostManager._stop_apis")
    def test_run_cleans_up_after_unexpected_server_exit(
        self,
        mock_stop_apis,
        mock_start_apis,
    ):
        self.server.is_running = False

        self.host.peer_server = Mock()
        self.host.peer_server.address = ("127.0.0.1", 8765)

        self.host.run()

        mock_start_apis.assert_called_once()
        self.manager.start.assert_called_once()
        self.manager.status.assert_called_once()
        mock_stop_apis.assert_called_once()

    @patch("mcsync.host_manager.HostManager._ensure_server_stopped")
    @patch("mcsync.host_manager.HostManager._start_apis")
    @patch("mcsync.host_manager.HostManager._stop_apis")
    def test_run_starts_apis_before_minecraft(
        self,
        mock_stop_apis,
        mock_start_apis,
        mock_ensure_stopped,
    ):
        events = []

        mock_start_apis.side_effect = lambda: events.append("apis")
        self.manager.start.side_effect = lambda: (
            events.append("minecraft") or self.server
        )

        mock_ensure_stopped.side_effect = lambda server: (
            setattr(server, "is_running", False)
        )

        self.host.peer_server = Mock()
        self.host.peer_server.address = ("127.0.0.1", 8765)

        self.host.run()

        self.assertEqual(events, ["apis", "minecraft"])
        mock_ensure_stopped.assert_called_once_with(self.server)
        mock_stop_apis.assert_called_once()

if __name__ == "__main__":
    unittest.main()
