import builtins
import queue
import tkinter as tk
import unittest
from pathlib import Path
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
            patch.object(TmusicApp, "_start_mpris", side_effect=lambda: startup_order.append("mpris")),
            patch.object(TmusicApp, "_tick"),
        ):
            TmusicApp(MagicMock())

        self.assertEqual(startup_order, ["tray", "mpris"])

    def test_super_q_binding_hides_window_and_stops_key_propagation(self) -> None:
        with patch("main.platform.system", return_value="Linux"):
            result = self.app._hide_window()

        self.app.root.withdraw.assert_called_once_with()
        self.assertEqual(result, "break")


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
