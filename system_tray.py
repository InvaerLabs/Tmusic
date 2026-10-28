from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from types import ModuleType
from typing import Protocol

from PIL import Image, ImageDraw


def _load_pystray() -> ModuleType:
    return import_module("pystray")


class SystemTrayIcon(Protocol):
    HAS_MENU: bool
    visible: bool

    def run_detached(self) -> None: ...

    def stop(self) -> None: ...


def create_system_tray(
    on_show: Callable[[], None],
    on_quit: Callable[[], None],
) -> SystemTrayIcon:
    pystray = _load_pystray()
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill="#151a19")
    draw.ellipse((16, 16, 48, 48), fill="#c3f27a")
    draw.ellipse((26, 26, 38, 38), fill="#151a19")

    def show(_icon: object, _item: object) -> None:
        on_show()

    def quit_app(_icon: object, _item: object) -> None:
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("Show Tmusic", show, default=True),
        pystray.MenuItem("Quit Tmusic", quit_app),
    )
    icon = pystray.Icon("tmusic", image, "Tmusic music player", menu)
    if not icon.HAS_MENU:
        raise RuntimeError("The selected system tray backend does not support menus.")
    return icon
