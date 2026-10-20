from __future__ import annotations

import json
import os
from pathlib import Path


def default_music_directory() -> Path:
    return Path.home() / "Music"


def preferences_path() -> Path:
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    ).expanduser()
    return config_home / "tmusic" / "settings.json"


def load_download_directory() -> Path:
    path = preferences_path()
    if not path.exists():
        return default_music_directory()

    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        directory = settings["download_directory"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError(f"Could not read Tmusic download settings: {error}") from error
    if not isinstance(directory, str) or not directory.strip():
        raise RuntimeError(f"Invalid download directory in Tmusic settings: {path}")
    return Path(directory).expanduser()


def save_download_directory(directory: Path) -> None:
    path = preferences_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"download_directory": str(directory)}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise RuntimeError(f"Could not save Tmusic download settings: {error}") from error
