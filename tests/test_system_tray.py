import unittest
import threading
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import utils.system_tray as system_tray


class SystemTrayTests(unittest.TestCase):
    def test_stop_hides_icon_before_stopping_it(self) -> None:
        icon = MagicMock()
        icon.visible = True

        system_tray.stop_system_tray(icon)

        self.assertFalse(icon.visible)
        icon.stop.assert_called_once_with()

    def test_stop_does_not_hide_an_already_hidden_icon(self) -> None:
        icon = MagicMock()
        icon.visible = False

        system_tray.stop_system_tray(icon)

        icon.stop.assert_called_once_with()

    def test_gtk_tray_hide_is_flushed_before_returning(self) -> None:
        calls: list[str] = []

        class GtkTrayIcon:
            __module__ = "pystray._appindicator"

            visible = True

            def __setattr__(self, name, value):
                if name == "visible" and value is False:
                    calls.append("hide")
                object.__setattr__(self, name, value)

            def stop(self):
                calls.append("stop")

        repository = ModuleType("gi.repository")
        repository.GLib = SimpleNamespace(
            idle_add=lambda callback: (calls.append("gtk-idle"), callback())
        )
        gi_module = ModuleType("gi")
        gi_module.repository = repository
        icon = GtkTrayIcon()

        with patch.dict(
            sys.modules,
            {"gi": gi_module, "gi.repository": repository},
        ):
            system_tray.stop_system_tray(icon)

        self.assertEqual(calls, ["hide", "gtk-idle", "stop"])

    def test_menu_actions_call_show_and_quit_callbacks(self) -> None:
        shown: list[bool] = []
        quit_requested: list[bool] = []
        quit_finished = threading.Event()
        toggled: list[bool] = []
        reversed_track: list[bool] = []
        advanced: list[bool] = []
        pystray = SimpleNamespace(
            MenuItem=MagicMock(
                side_effect=lambda label, action, **kwargs: (label, action, kwargs)
            ),
            Menu=MagicMock(side_effect=lambda *items: items),
            Icon=MagicMock(),
        )

        with patch("utils.system_tray._load_pystray", return_value=pystray):
            icon = system_tray.create_system_tray(
                lambda: shown.append(True),
                lambda: (quit_requested.append(True), quit_finished.set()),
                lambda: toggled.append(True),
                lambda: reversed_track.append(True),
                lambda: advanced.append(True),
            )

        self.assertIs(icon, pystray.Icon.return_value)
        self.assertEqual(pystray.Icon.call_args.args[0], "Tmusic")
        menu = pystray.Icon.call_args.args[3]
        self.assertEqual(
            [item[0] for item in menu if isinstance(item, tuple)],
            [
                "Open Tmusic",
                "Play / Pause",
                "Previous track",
                "Next track",
                "Quit Tmusic",
            ],
        )
        menu[0][1](icon, None)
        menu[1][1](icon, None)
        menu[2][1](icon, None)
        menu[3][1](icon, None)
        menu[-1][1](icon, None)
        self.assertTrue(quit_finished.wait(timeout=1))

        self.assertEqual(shown, [True])
        self.assertEqual(toggled, [True])
        self.assertEqual(reversed_track, [True])
        self.assertEqual(advanced, [True])
        self.assertEqual(quit_requested, [True])


if __name__ == "__main__":
    unittest.main()
