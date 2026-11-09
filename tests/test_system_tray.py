import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import system_tray


class SystemTrayTests(unittest.TestCase):
    def test_menu_actions_call_show_and_quit_callbacks(self) -> None:
        shown: list[bool] = []
        quit_requested: list[bool] = []
        pystray = SimpleNamespace(
            MenuItem=MagicMock(side_effect=lambda label, action, **_kwargs: (label, action)),
            Menu=MagicMock(side_effect=lambda *items: items),
            Icon=MagicMock(),
        )

        with patch("system_tray._load_pystray", return_value=pystray):
            icon = system_tray.create_system_tray(
                lambda: shown.append(True),
                lambda: quit_requested.append(True),
            )

        self.assertIs(icon, pystray.Icon.return_value)
        menu = pystray.Icon.call_args.args[3]
        menu[0][1](icon, None)
        menu[1][1](icon, None)

        self.assertEqual(shown, [True])
        self.assertEqual(quit_requested, [True])


if __name__ == "__main__":
    unittest.main()
