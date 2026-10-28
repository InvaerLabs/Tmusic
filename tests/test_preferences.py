import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from preferences import (
    default_music_directory,
    load_download_directory,
    load_music_folders,
    load_show_cover,
    load_theme_preference,
    save_download_directory,
    save_music_folders,
    save_show_cover,
    save_theme_preference,
    system_theme,
)


@contextmanager
def isolated_preferences(directory: str) -> Iterator[Path]:
    settings_file = Path(directory) / "tmusic" / "settings.json"
    with patch("preferences.preferences_path", return_value=settings_file):
        yield settings_file


class DownloadDirectoryPreferenceTests(unittest.TestCase):
    def test_default_is_home_music(self) -> None:
        with patch("preferences.Path.home", return_value=Path("/home/test-user")):
            self.assertEqual(default_music_directory(), Path("/home/test-user/Music"))

    def test_load_defaults_to_home_music_without_saved_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                isolated_preferences(temporary_directory),
                patch("preferences.Path.home", return_value=Path("/home/test-user")),
            ):
                self.assertEqual(
                    load_download_directory(),
                    Path("/home/test-user/Music"),
                )

    def test_saved_destination_is_loaded_on_next_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory) as settings_file:
                destination = Path(temporary_directory) / "Audio"
                save_download_directory(destination)

                self.assertEqual(load_download_directory(), destination)
                settings = json.loads(settings_file.read_text(encoding="utf-8"))
                self.assertEqual(settings["download_directory"], str(destination))

    def test_invalid_saved_settings_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory) as path:
                path.parent.mkdir(parents=True)
                path.write_text("{not valid json", encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, "Could not read"):
                    load_download_directory()

    def test_theme_preference_is_saved_alongside_download_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory):
                destination = Path(temporary_directory) / "Music"
                save_download_directory(destination)
                save_theme_preference("light")

                self.assertEqual(load_download_directory(), destination)
                self.assertEqual(load_theme_preference(), "light")

    def test_music_folders_and_cover_preference_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory):
                folders = [Path(temporary_directory) / "Music", Path(temporary_directory) / "Extra"]
                save_music_folders(folders)
                save_show_cover(False)

                self.assertEqual(load_music_folders(), folders)
                self.assertFalse(load_show_cover())

    def test_unset_music_folders_use_application_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory):
                self.assertIsNone(load_music_folders())
                self.assertTrue(load_show_cover())

    def test_invalid_music_folder_setting_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory) as settings_file:
                settings_file.parent.mkdir(parents=True)
                settings_file.write_text(
                    json.dumps({"music_folders": ["", 42]}), encoding="utf-8"
                )
                with self.assertRaisesRegex(RuntimeError, "Invalid music folders"):
                    load_music_folders()

    def test_unknown_theme_preference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with isolated_preferences(temporary_directory) as settings_file:
                settings_file.parent.mkdir(parents=True)
                settings_file.write_text(
                    json.dumps({"theme": "sepia"}), encoding="utf-8"
                )
                with self.assertRaisesRegex(RuntimeError, "Invalid Tmusic theme"):
                    load_theme_preference()

    def test_system_theme_uses_gtk_theme_environment_when_present(self) -> None:
        with (
            patch("preferences.platform.system", return_value="Linux"),
            patch.dict(os.environ, {"GTK_THEME": "Adwaita:light"}),
        ):
            self.assertEqual(system_theme(), "light")


if __name__ == "__main__":
    unittest.main()
