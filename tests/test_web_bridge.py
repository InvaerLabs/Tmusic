import base64
import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Thread
from unittest.mock import MagicMock, call, patch

from PIL import Image

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ui.web_bridge import (
    TmusicBridge,
    _CoreClient,
    _CoreHTTPServer,
    _WebViewAPI,
    _asset_directory,
)


class BridgePreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        folder = Path(self.temporary_directory.name)
        self.settings_patch = patch.multiple(
            "ui.web_bridge",
            load_download_directory=MagicMock(return_value=folder),
            load_music_folders=MagicMock(return_value=[folder]),
            load_mp3_bitrate=MagicMock(return_value=256),
            load_theme_preference=MagicMock(return_value="stars"),
            discover_tracks=MagicMock(return_value=[]),
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_initial_state_includes_saved_preferences_and_empty_library(self) -> None:
        bridge = TmusicBridge()

        state = bridge.get_state()

        self.assertEqual(state["bitrate"], 256)
        self.assertEqual(state["theme"], "stars")
        self.assertEqual(state["tracks"], [])
        self.assertEqual(
            state["folders"],
            [str(Path.home() / "Music"), self.temporary_directory.name],
        )

    def test_unchanged_state_omits_heavy_track_lyrics_and_cover_payloads(self) -> None:
        bridge = TmusicBridge()

        initial = bridge.get_state()
        unchanged = bridge.get_state()

        self.assertIn("tracks", initial)
        self.assertIn("lyrics", initial)
        self.assertIn("cover", initial)
        self.assertNotIn("tracks", unchanged)
        self.assertNotIn("lyrics", unchanged)
        self.assertNotIn("cover", unchanged)

        bridge.refresh_library()
        refreshed = bridge.get_state()
        self.assertIn("tracks", refreshed)
        self.assertIn("lyrics", refreshed)

        reopened = bridge.get_state(full=True)
        self.assertIn("tracks", reopened)
        self.assertIn("lyrics", reopened)
        self.assertIn("cover", reopened)

    def test_bitrate_choice_is_validated_and_persisted(self) -> None:
        bridge = TmusicBridge()
        with patch("ui.web_bridge.save_mp3_bitrate") as save:
            bridge.set_bitrate("192")
            save.assert_called_once_with(192)
        self.assertEqual(bridge.bitrate, 192)
        with self.assertRaises(ValueError):
            bridge.set_bitrate("128")

    def test_theme_selection_is_saved(self) -> None:
        bridge = TmusicBridge()
        with patch("ui.web_bridge.save_theme_preference") as save:
            bridge.set_theme("light")
        save.assert_called_once_with("light")
        self.assertEqual(bridge.theme, "light")

    def test_cover_preview_is_reduced_for_the_player_ui(self) -> None:
        image_data = BytesIO()
        Image.new("RGB", (1600, 1200), (80, 120, 160)).save(
            image_data,
            format="PNG",
        )

        preview = TmusicBridge._cover_preview(image_data.getvalue())

        mime, encoded = preview.split(",", 1)
        self.assertEqual(mime, "data:image/jpeg;base64")
        with Image.open(BytesIO(base64.b64decode(encoded))) as image:
            self.assertLessEqual(max(image.size), 512)


class BridgePlaybackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        folder = Path(self.temporary_directory.name)
        self.patchers = [
            patch("ui.web_bridge.load_download_directory", return_value=folder),
            patch("ui.web_bridge.load_music_folders", return_value=[folder]),
            patch("ui.web_bridge.load_mp3_bitrate", return_value=320),
            patch("ui.web_bridge.load_theme_preference", return_value="system"),
            patch("ui.web_bridge.discover_tracks", return_value=[]),
        ]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)

    def test_shuffle_and_repeat_settings_reach_player(self) -> None:
        bridge = TmusicBridge()

        bridge.set_shuffle(True)
        bridge.set_repeat("one")

        self.assertTrue(bridge.player.shuffle)
        self.assertEqual(bridge.player.repeat_mode, "one")
        with self.assertRaises(ValueError):
            bridge.set_repeat("loop")

    def test_platform_commands_are_applied_on_state_poll(self) -> None:
        bridge = TmusicBridge()

        bridge._queue_command("volume", 0.4)
        bridge._queue_command("shuffle", True)
        bridge.get_state()

        self.assertEqual(bridge.player.volume, 0.4)
        self.assertTrue(bridge.player.shuffle)

    def test_command_worker_processes_media_commands_without_ui_polling(self) -> None:
        bridge = TmusicBridge()
        processed = Event()
        set_volume = bridge.player.set_volume

        def capture_volume(value: float) -> None:
            set_volume(value)
            processed.set()

        bridge.player.set_volume = capture_volume
        worker = Thread(target=bridge._run_command_worker, daemon=True)
        worker.start()
        try:
            bridge._queue_command("volume", 0.4)
            self.assertTrue(processed.wait(timeout=1))
            self.assertEqual(bridge.player.volume, 0.4)
        finally:
            with bridge._lock:
                bridge._closed = True
            bridge._commands.put(("wake", None))
            worker.join(timeout=1)
        self.assertFalse(worker.is_alive())

    def test_failed_track_selection_reports_error(self) -> None:
        bridge = TmusicBridge()

        self.assertFalse(bridge.play_track("/missing/song.mp3"))
        self.assertIn("Could not play track", bridge.get_state()["error"])


class BridgeDialogAndEditorTests(unittest.TestCase):
    def test_new_webview_gets_a_full_snapshot_once(self) -> None:
        bridge = object.__new__(_WebViewAPI)
        bridge._client = MagicMock()
        bridge._initial_state = True
        bridge._close_approved = False
        bridge._client.call.return_value = {"tracks": [], "lyrics": [], "cover": None}

        bridge.get_state()
        bridge.get_state()

        self.assertEqual(
            bridge._client.call.call_args_list,
            [call("get_state", True), call("get_state", False)],
        )

    def test_dialog_normalizes_single_and_multiple_selection(self) -> None:
        bridge = object.__new__(_WebViewAPI)
        bridge.window = MagicMock()
        bridge._window_x = 0
        bridge._window_y = 0
        bridge._drag_origin = (0, 0)
        bridge._initial_state = True
        bridge._close_approved = False
        bridge.window.create_file_dialog.return_value = ["/music"]

        selected = bridge._dialog(20, directory="/home")

        self.assertEqual(selected, "/music")
        bridge.window.create_file_dialog.assert_called_once_with(20, directory="/home")

    def test_editor_restores_current_track_after_failed_save(self) -> None:
        bridge = object.__new__(TmusicBridge)
        track = Path("/music/song.mp3")
        bridge.player = MagicMock()
        bridge.player.current_track = track
        bridge.player.is_playing = True
        bridge._last_error = None
        bridge._resume_after_edit = MagicMock()
        with patch("ui.web_bridge.save_mp3_metadata", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                bridge.save_editor(str(track), "Song", "Artist", "", None)

        bridge.player.stop.assert_called_once_with()
        bridge.player.unload.assert_called_once_with()
        bridge._resume_after_edit.assert_called_once_with(track, True)


class BridgeDownloadTests(unittest.TestCase):
    def test_download_starts_worker_with_url_and_cancellation_event(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._lock = Lock()
        bridge._download_active = False
        bridge._download_cancel = Event()
        bridge._download_progress = {}
        bridge._download_error = None
        bridge._download_finished = None
        with patch("ui.web_bridge.threading.Thread") as thread:
            self.assertTrue(bridge.start_download(" https://example.test/audio "))

        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"], ("https://example.test/audio",))
        self.assertTrue(bridge._download_active)
        self.assertEqual(thread.call_args.kwargs["target"], bridge._download_worker)

    def test_empty_download_url_is_rejected(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._download_active = False
        with self.assertRaises(ValueError):
            bridge.start_download(" ")

    def test_cancel_download_signals_worker(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._download_cancel = Event()

        bridge.cancel_download()

        self.assertTrue(bridge._download_cancel.is_set())


class BridgeLifecycleTests(unittest.TestCase):
    def test_drag_moves_frameless_window_relative_to_drag_start(self) -> None:
        bridge = object.__new__(_WebViewAPI)
        bridge.window = MagicMock()

        bridge.attach_window(bridge.window, 100, 200)
        bridge.begin_window_drag()
        bridge.move_window_drag(14, -8)

        bridge.window.move.assert_called_once_with(114, 192)

    def test_close_stops_services_and_player_once(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._lock = Lock()
        bridge._closed = False
        bridge._download_cancel = Event()
        bridge._service = MagicMock()
        bridge._service_thread = None
        bridge._command_thread = None
        bridge._download_thread = None
        bridge._tray_icon = MagicMock()
        bridge.player = MagicMock()
        bridge._ui_process = None
        bridge._ui_lock = Lock()
        bridge._ipc_server = None
        bridge._ipc_thread = None
        bridge._shutdown = Event()

        bridge.close()
        bridge.close()

        self.assertTrue(bridge._download_cancel.is_set())
        self.assertTrue(bridge._shutdown.is_set())
        bridge._service.stop.assert_called_once_with()
        bridge.player.shutdown.assert_called_once_with()

    def test_ui_close_does_not_close_the_background_core(self) -> None:
        bridge = object.__new__(_WebViewAPI)
        bridge._client = MagicMock()
        bridge._client.call.return_value = {}
        bridge.window = MagicMock()
        bridge._initial_state = True
        bridge._close_approved = False

        self.assertTrue(bridge.on_window_closing())
        bridge.on_window_closed()

        self.assertEqual(
            bridge._client.call.call_args_list,
            [call("get_state", True), call("ui_closed")],
        )
        bridge.window.destroy.assert_not_called()

    def test_native_close_prompts_before_cancelling_a_download(self) -> None:
        bridge = object.__new__(_WebViewAPI)
        bridge._client = MagicMock()
        bridge._client.call.return_value = {"download": {"active": True}}
        bridge._initial_state = False
        bridge._close_approved = False
        bridge.window = MagicMock()
        bridge.window.create_confirmation_dialog.return_value = False

        self.assertFalse(bridge.on_window_closing())

        bridge.window.create_confirmation_dialog.assert_called_once()
        bridge._client.call.assert_called_once_with("get_state", False)

        bridge.window.create_confirmation_dialog.return_value = True
        self.assertTrue(bridge.on_window_closing())
        self.assertEqual(
            bridge._client.call.call_args_list[-1:],
            [call("cancel_download")],
        )
        bridge.on_window_closed()
        bridge._client.call.assert_called_with("ui_closed")

    def test_ui_close_quits_core_only_when_tray_is_unavailable(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._ui_lock = Lock()
        bridge._tray_icon = None
        bridge.request_close = MagicMock()

        bridge.ui_closed()

        bridge.request_close.assert_called_once_with()

    def test_ui_close_releases_child_handle_for_next_tray_open(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._ui_lock = Lock()
        bridge._ui_process = MagicMock()
        bridge._tray_icon = MagicMock()
        bridge.request_close = MagicMock()

        bridge.ui_closed()

        self.assertIsNone(bridge._ui_process)
        bridge.request_close.assert_not_called()

    def test_closing_ui_destroys_webview_and_keeps_core_running(self) -> None:
        bridge = object.__new__(_WebViewAPI)
        bridge._client = MagicMock()
        bridge.window = MagicMock()
        bridge._close_approved = False

        bridge.hide_window()
        bridge.on_window_closed()

        bridge._client.call.assert_called_once_with("ui_closed")
        bridge.window.destroy.assert_called_once_with()

    def test_show_window_launches_ui_child_with_authenticated_ipc(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._ipc_server = MagicMock()
        bridge._ipc_server.server_address = ("127.0.0.1", 43210)
        bridge._ipc_token = "test-token"
        bridge._ui_lock = Lock()
        bridge._ui_process = None
        bridge._closed = False

        with patch("ui.web_bridge.subprocess.Popen") as popen:
            bridge.show_window()

        command = popen.call_args.args[0]
        self.assertIn("--tmusic-ui", command)
        self.assertEqual(command[-3:], ["127.0.0.1", "43210", "test-token"])

    def test_core_client_uses_allowlisted_authenticated_ipc(self) -> None:
        bridge = MagicMock()
        bridge.refresh_library.return_value = None
        server = _CoreHTTPServer(("127.0.0.1", 0), bridge, "test-token")
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.shutdown)
        client = _CoreClient("127.0.0.1", server.server_address[1], "test-token")

        self.assertIsNone(client.call("refresh_library"))
        bridge.refresh_library.assert_called_once_with()
        with self.assertRaises(ValueError):
            client.call("close")
        unauthorized = _CoreClient(
            "127.0.0.1",
            server.server_address[1],
            "wrong-token",
        )
        with self.assertRaisesRegex(RuntimeError, "Unauthorized"):
            unauthorized.call("refresh_library")

    def test_asset_directory_uses_packaged_or_source_assets(self) -> None:
        asset_directory = _asset_directory()

        self.assertEqual(asset_directory.name, "dist")
        self.assertEqual(asset_directory.parent.name, "webui")


class UpdateCheckTests(unittest.TestCase):
    def test_update_worker_reports_newer_release(self) -> None:
        bridge = object.__new__(TmusicBridge)
        bridge._lock = Lock()
        bridge._update_checking = True
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "tag_name": "v3.1.0",
                "html_url": "https://github.com/InvaerLabs/Tmusic/releases/tag/v3.1.0",
            }
        ).encode()

        with patch("ui.web_bridge.urllib.request.urlopen", return_value=response):
            bridge._check_update_worker()

        self.assertEqual(bridge._update_result["kind"], "available")
        self.assertFalse(bridge._update_checking)

    def test_release_links_are_limited_to_official_repository(self) -> None:
        bridge = object.__new__(TmusicBridge)
        with self.assertRaises(ValueError):
            bridge.open_release("https://example.test/releases/v3")


if __name__ == "__main__":
    unittest.main()
