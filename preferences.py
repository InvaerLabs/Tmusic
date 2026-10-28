from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path


def default_music_directory() -> Path:
    return Path.home() / "Music"


def _config_directory() -> Path:
    env_dir = os.environ.get("TMUSIC_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser()

    if os.name == "nt":
        config_home = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif platform.system() == "Darwin":
        config_home = Path.home() / "Library" / "Application Support"
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home.expanduser() / "tmusic"


def preferences_path() -> Path:
    return _config_directory() / "settings.json"


def _read_settings() -> dict[str, object]:
    path = preferences_path()
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read Tmusic settings: {error}") from error
    if not isinstance(settings, dict):
        raise RuntimeError(f"Invalid Tmusic settings in {path}")
    return settings


def _write_settings(settings: dict[str, object]) -> None:
    path = preferences_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"Could not save Tmusic settings: {error}") from error


def load_download_directory() -> Path:
    settings = _read_settings()
    directory = settings.get("download_directory")
    if directory is None:
        return default_music_directory()
    if not isinstance(directory, str) or not directory.strip():
        raise RuntimeError(f"Invalid download directory in Tmusic settings: {preferences_path()}")
    return Path(directory).expanduser()


def save_download_directory(directory: Path) -> None:
    settings = _read_settings()
    settings["download_directory"] = str(directory)
    _write_settings(settings)


def load_music_folders() -> list[Path] | None:
    folders = _read_settings().get("music_folders")
    if folders is None:
        return None
    if not isinstance(folders, list) or not all(
        isinstance(folder, str) and folder.strip() for folder in folders
    ):
        raise RuntimeError(f"Invalid music folders in Tmusic settings: {preferences_path()}")
    return list(dict.fromkeys(Path(folder).expanduser() for folder in folders))


def save_music_folders(folders: list[Path]) -> None:
    settings = _read_settings()
    settings["music_folders"] = [str(folder) for folder in dict.fromkeys(folders)]
    _write_settings(settings)


def load_show_cover() -> bool:
    value = _read_settings().get("show_cover", True)
    if not isinstance(value, bool):
        raise RuntimeError(f"Invalid cover display setting in Tmusic settings: {value!r}")
    return value


def save_show_cover(show_cover: bool) -> None:
    settings = _read_settings()
    settings["show_cover"] = show_cover
    _write_settings(settings)


THEMES = ("system", "light", "dark", "stars")


def load_theme_preference() -> str:
    theme = _read_settings().get("theme", "system")
    if not isinstance(theme, str) or theme not in THEMES:
        raise RuntimeError(f"Invalid Tmusic theme preference: {theme!r}")
    return theme


def save_theme_preference(theme: str) -> None:
    if theme not in THEMES:
        raise ValueError("Theme must be system, light, dark, or stars.")
    settings = _read_settings()
    settings["theme"] = theme
    _write_settings(settings)


def system_theme() -> str:
    system = platform.system()
    if system == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        except (ImportError, OSError):
            return "light"
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return "light"
        return "dark" if result.returncode == 0 and "dark" in result.stdout.casefold() else "light"

    gtk_theme = os.environ.get("GTK_THEME", "").casefold()
    if "dark" in gtk_theme:
        return "dark"
    if "light" in gtk_theme:
        return "light"
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "dark"
    return "light" if "prefer-light" in result.stdout.casefold() else "dark"
