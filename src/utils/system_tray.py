from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
import threading
from types import ModuleType
from typing import Protocol

from PIL import Image

from utils.resources import resource_path


def _load_pystray() -> ModuleType:
    return import_module("pystray")


class SystemTrayIcon(Protocol):
    HAS_MENU: bool
    visible: bool

    def run_detached(self, setup: Callable[[SystemTrayIcon], None] | None = None) -> None: ...

    def stop(self) -> None: ...


def stop_system_tray(icon: SystemTrayIcon) -> None:
    if icon.visible:
        icon.visible = False

    backend = type(icon).__module__
    hidden: threading.Event | None = None
    if backend.endswith("._gtk") or backend.endswith("._appindicator"):
        from gi.repository import GLib

        hidden = threading.Event()
        GLib.idle_add(hidden.set)

    icon.stop()
    if hidden is not None and not hidden.wait(timeout=2):
        raise RuntimeError("The tray icon did not finish hiding before shutdown.")


def create_system_tray(
    on_show: Callable[[], None],
    on_quit: Callable[[], None],
    on_play_pause: Callable[[], None] | None = None,
    on_previous: Callable[[], None] | None = None,
    on_next: Callable[[], None] | None = None,
) -> SystemTrayIcon:
    pystray = _load_pystray()
    logo_path = resource_path("Logo.jpeg")
    if not logo_path.is_file():
        raise FileNotFoundError(f"Tmusic tray icon artwork was not found: {logo_path}")
    with Image.open(logo_path) as source:
        image = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)

    def show(_icon: object, _item: object) -> None:
        on_show()

    def quit_app(_icon: object, _item: object) -> None:
        threading.Thread(
            target=on_quit,
            name="tmusic-tray-quit",
            daemon=True,
        ).start()

    menu_items = [pystray.MenuItem("Open Tmusic", show, default=True)]
    if on_play_pause is not None:
        menu_items.append(
            pystray.MenuItem("Play / Pause", lambda _icon, _item: on_play_pause())
        )
    if on_previous is not None:
        menu_items.append(
            pystray.MenuItem("Previous track", lambda _icon, _item: on_previous())
        )
    if on_next is not None:
        menu_items.append(
            pystray.MenuItem("Next track", lambda _icon, _item: on_next())
        )
    menu_items.extend(
        [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Tmusic", quit_app),
        ]
    )
    menu = pystray.Menu(*menu_items)
    icon = pystray.Icon("Tmusic", image, "Tmusic music player", menu)
    if not icon.HAS_MENU:
        raise RuntimeError("The selected system tray backend does not support menus.")
    return icon
