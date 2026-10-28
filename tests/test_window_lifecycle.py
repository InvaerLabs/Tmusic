import builtins
import json
import queue
import tkinter as tk
import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import MagicMock, patch

from main import TmusicApp


class LinuxWindowLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = object.__new__(TmusicApp)
        self.app.root = MagicMock()
        self.app._tray_icon = MagicMock()
        self.app._background_messages = queue.SimpleQueue()

    def test_close_button_hides_window_without_stopping_application(self) -> None:
        with patch("main.platform.system", return_value="Linux"):
            self.app._on_close()

        self.app.root.withdraw.assert_called_once_with()
        self.app.root.destroy.assert_not_called()

    def test_close_exits_when_tray_is_unavailable(self) -> None:
        self.app._tray_icon = None
        self.app._tray_error = "no tray backend"
        self.app.close = MagicMock()
        with (
            patch("main.platform.system", return_value="Linux"),
            patch("main.messagebox.showwarning") as showwarning,
        ):
            self.app._on_close()

        showwarning.assert_called_once()
        self.app.close.assert_called_once_with()

    def test_tray_startup_makes_icon_visible(self) -> None:
        tray_icon = MagicMock()
        with patch("system_tray.create_system_tray", return_value=tray_icon):
            self.app._start_system_tray()

        tray_icon.run_detached.assert_called_once_with()
        self.assertTrue(tray_icon.visible)

    def test_tray_import_failure_does_not_prevent_player_startup(self) -> None:
        original_import = builtins.__import__

        def fail_tray_import(name, *args, **kwargs):
            if name == "system_tray":
                raise AttributeError("'gi.repository.GLib' object has no attribute 'Idle'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_tray_import):
            self.app._start_system_tray()

        self.assertIsNone(self.app._tray_icon)
        self.assertIn("GLib", self.app._tray_error)
        self.assertIn("System tray unavailable", self.app._background_messages.get_nowait())

    def test_tray_initializes_before_mpris_thread(self) -> None:
        startup_order: list[str] = []
        def start_media_controls(app: TmusicApp) -> None:
            self.assertIsNotNone(app._media_service_lock)
            self.assertIsNone(app._media_service)
            self.assertIsNone(app._media_service_thread)
            startup_order.append("mpris")

        with (
            patch("main.MusicPlayer"),
            patch("main.Downloader"),
            patch("main.load_download_directory", return_value=Path.home() / "Music"),
            patch("main.load_theme_preference", return_value="system"),
            patch("main.system_theme", return_value="dark"),
            patch("main.platform.system", return_value="Linux"),
            patch.object(TmusicApp, "_build_ui"),
            patch.object(TmusicApp, "_apply_theme"),
            patch.object(TmusicApp, "refresh_library"),
            patch.object(TmusicApp, "_bind_shortcuts"),
            patch.object(TmusicApp, "_start_system_tray", side_effect=lambda: startup_order.append("tray")),
            patch.object(TmusicApp, "_start_media_controls", start_media_controls),
            patch.object(TmusicApp, "_tick"),
        ):
            TmusicApp(MagicMock())

        self.assertEqual(startup_order, ["tray", "mpris"])

    def test_play_selection_uses_lyrics_loaded_by_player(self) -> None:
        app = object.__new__(TmusicApp)
        track = Path("/music/song.mp3")
        app.player = MagicMock()
        app.player.current_track = track
        app._sync_displayed_track = MagicMock()
        app._set_status = MagicMock()
        app._update_play_button = MagicMock()

        app._play_index(0)

        app.player.play_index.assert_called_once_with(0)
        app._sync_displayed_track.assert_called_once_with()
        app._set_status.assert_called_once_with("Playing song.mp3")

    def test_super_q_binding_hides_window_and_stops_key_propagation(self) -> None:
        with patch("main.platform.system", return_value="Linux"):
            result = self.app._hide_window()

        self.app.root.withdraw.assert_called_once_with()
        self.assertEqual(result, "break")

    def test_media_controls_select_only_current_platform_service(self) -> None:
        app = object.__new__(TmusicApp)
        with (
            patch("main.platform.system", return_value="Windows"),
            patch.object(app, "_start_mpris") as start_mpris,
            patch.object(app, "_start_smtc") as start_smtc,
            patch.object(app, "_start_now_playing") as start_now_playing,
        ):
            app._start_media_controls()

        start_mpris.assert_not_called()
        start_smtc.assert_called_once_with()
        start_now_playing.assert_not_called()

    def test_media_service_is_created_and_started_by_worker(self) -> None:
        app = object.__new__(TmusicApp)
        app.player = MagicMock()
        app._closing = False
        app._media_service_lock = Lock()
        app._media_service = None
        service = MagicMock()
        module = MagicMock(create_service=MagicMock(return_value=service))
        with (
            patch("main.threading.Thread") as thread,
            patch("main.importlib.import_module", return_value=module),
        ):
            app._start_media_service("MPRIS", "MPRIS")
            thread.call_args.kwargs["target"]()

        module.create_service.assert_called_once()
        service.start.assert_called_once_with()
        self.assertIsNone(app._media_service)

    def test_close_stops_media_service_before_shutting_down_player(self) -> None:
        app = object.__new__(TmusicApp)
        app._closing = False
        app._media_service_lock = Lock()
        media_service = MagicMock()
        app._media_service = media_service
        app._media_service_thread = MagicMock()
        app._tray_icon = None
        app.player = MagicMock()
        app.root = MagicMock()

        app.close()

        media_service.stop.assert_called_once_with()
        app._media_service_thread.join.assert_called_once_with(timeout=1)
        app.player.shutdown.assert_called_once_with()
        app.root.destroy.assert_called_once_with()


class UpdateCheckTests(unittest.TestCase):
    def test_update_worker_reports_a_newer_github_release(self) -> None:
        app = object.__new__(TmusicApp)
        app._update_messages = queue.SimpleQueue()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "tag_name": "v3.1.0",
                "html_url": "https://github.com/InvaerLabs/Tmusic/releases/tag/v3.1.0",
            }
        ).encode()
        with patch("main.urllib.request.urlopen", return_value=response):
            app._check_update_worker()

        self.assertEqual(
            app._update_messages.get_nowait(),
            (
                "available",
                "v3.1.0",
                "https://github.com/InvaerLabs/Tmusic/releases/tag/v3.1.0",
            ),
        )

    def test_equal_v3_release_is_not_reported_as_an_update(self) -> None:
        app = object.__new__(TmusicApp)
        app._update_messages = queue.SimpleQueue()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "tag_name": "v3.0",
                "html_url": "https://github.com/InvaerLabs/Tmusic/releases/tag/v3.0",
            }
        ).encode()
        with patch("main.urllib.request.urlopen", return_value=response):
            app._check_update_worker()

        self.assertEqual(
            app._update_messages.get_nowait(),
            (
                "current",
                "v3.0",
                "https://github.com/InvaerLabs/Tmusic/releases/tag/v3.0",
            ),
        )


class ClipboardDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = object.__new__(TmusicApp)
        self.app.root = MagicMock()
        self.app.download_status = MagicMock()
        self.app.download_button = MagicMock()
        self.app.download_progress = MagicMock()
        self.app._download_active = False
        self.app._download_messages = MagicMock()

    def test_paste_and_download_uses_clipboard_url(self) -> None:
        self.app.root.clipboard_get.return_value = " https://example.com/audio "
        with patch("main.threading.Thread") as thread:
            self.app.start_download()

        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"], ("https://example.com/audio",))

    def test_empty_clipboard_does_not_start_download(self) -> None:
        self.app.root.clipboard_get.side_effect = tk.TclError("clipboard empty")
        with patch("main.threading.Thread") as thread:
            self.app.start_download()

        thread.assert_not_called()
        self.app.download_status.configure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
