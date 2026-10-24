import unittest
from unittest.mock import patch

from system_tray import create_system_tray


class SystemTrayTests(unittest.TestCase):
    def test_menu_actions_call_show_and_quit_callbacks(self) -> None:
        shown: list[bool] = []
        quit_requested: list[bool] = []

        with (
            patch(
                "system_tray.pystray.MenuItem",
                side_effect=lambda label, action, **_kwargs: (label, action),
            ),
            patch("system_tray.pystray.Menu", side_effect=lambda *items: items),
            patch("system_tray.pystray.Icon") as icon_factory,
        ):
            icon = create_system_tray(
                lambda: shown.append(True),
                lambda: quit_requested.append(True),
            )

        self.assertIs(icon, icon_factory.return_value)
        menu = icon_factory.call_args.args[3]
        menu[0][1](icon, None)
        menu[1][1](icon, None)

        self.assertEqual(shown, [True])
        self.assertEqual(quit_requested, [True])


if __name__ == "__main__":
    unittest.main()
