import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from player import (
    LyricLine,
    MusicPlayer,
    discover_tracks,
    format_time,
    parse_lrc,
    read_track_lyrics,
    save_mp3_metadata,
)


class ParseLrcTests(unittest.TestCase):
    def test_parses_multiple_timestamps_and_sorts_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lyrics_file = Path(temporary_directory) / "song.lrc"
            lyrics_file.write_text(
                "[00:03.25][00:01.50]First line\n[00:04.00]Second line\n",
                encoding="utf-8",
            )

            self.assertEqual(
                parse_lrc(lyrics_file),
                [
                    LyricLine(1.5, "First line"),
                    LyricLine(3.25, "First line"),
                    LyricLine(4.0, "Second line"),
                ],
            )

    def test_applies_offset_and_ignores_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lyrics_file = Path(temporary_directory) / "song.lrc"
            lyrics_file.write_text(
                "[ar:Example]\n[offset:-250]\n[01:02.5]A line\n",
                encoding="utf-8",
            )

            self.assertEqual(parse_lrc(lyrics_file), [LyricLine(62.25, "A line")])

    def test_clamps_negative_offset_and_ignores_invalid_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lyrics_file = Path(temporary_directory) / "song.lrc"
            lyrics_file.write_text(
                "[offset:-1000]\n[00:00.20]First\n[00:60.00]Invalid\n",
                encoding="utf-8",
            )

            self.assertEqual(parse_lrc(lyrics_file), [LyricLine(0.0, "First")])


class LibraryHelpersTests(unittest.TestCase):
    def test_discovers_supported_audio_recursively_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            nested = root / "nested"
            nested.mkdir()
            (root / "track.MP3").touch()
            (nested / "other.ogg").touch()
            (root / "cover.jpg").touch()

            self.assertEqual(
                discover_tracks([root, nested]),
                [(nested / "other.ogg").resolve(), (root / "track.MP3").resolve()],
            )

    def test_formats_track_times(self) -> None:
        self.assertEqual(format_time(65.9), "01:05")
        self.assertEqual(format_time(None), "--:--")

    def test_embeds_synced_lyrics_and_updates_mp3_title_and_artist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            original = Path(temporary_directory) / "old-title.mp3"
            original.touch()

            renamed = save_mp3_metadata(
                original,
                title="New title",
                artist="New artist",
                lrc_text="[00:01.25]First lyric\n[00:02.50]Second lyric\n",
            )

            self.assertEqual(renamed, Path(temporary_directory) / "New title.mp3")
            lyrics, synchronized = read_track_lyrics(renamed)
            self.assertTrue(synchronized)
            self.assertEqual(
                lyrics,
                [LyricLine(1.25, "First lyric"), LyricLine(2.5, "Second lyric")],
            )

    def test_non_mp3_without_sidecar_does_not_attempt_id3_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            track = Path(temporary_directory) / "track.flac"
            track.touch()
            with patch("player.ID3") as id3:
                self.assertEqual(read_track_lyrics(track), ([], False))
            id3.assert_not_called()

    def test_invalid_filename_title_is_rejected_before_changing_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            track = Path(temporary_directory) / "track.mp3"
            track.touch()
            with patch("player.ID3") as id3:
                with self.assertRaises(ValueError):
                    save_mp3_metadata(track, title="...", artist="", lrc_text="")
            id3.assert_not_called()


class MusicPlayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mocks = [
            patch("player.pygame.mixer.init"),
            patch("player.pygame.mixer.music.set_volume"),
            patch("player.pygame.mixer.music.load"),
            patch("player.pygame.mixer.music.play"),
            patch("player.pygame.mixer.music.unpause"),
            patch("player.pygame.mixer.music.pause"),
            patch("player.pygame.mixer.music.stop"),
            patch("player.pygame.mixer.music.get_pos", return_value=0),
            patch("player.pygame.mixer.music.get_busy", return_value=True),
            patch(
                "player.MutagenFile",
                side_effect=lambda path, easy=False: SimpleNamespace(
                    info=None if easy or not path else SimpleNamespace(length=120),
                    tags=None,
                ),
            ),
            patch(
                "player.read_track_lyrics",
                side_effect=lambda path: (
                    read_track_lyrics(path) if path.exists() else ([], False)
                ),
            ),
        ]
        for mock in self.mocks:
            mock.start()
        self.addCleanup(patch.stopall)
        self.player = MusicPlayer()
        self.player.set_library(
            [Path("first.mp3"), Path("second.mp3"), Path("third.mp3")]
        )

    def test_player_scans_embedded_artist_and_synced_lyrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            original = Path(temporary_directory) / "track.mp3"
            original.touch()
            track = save_mp3_metadata(
                original,
                title="Embedded title",
                artist="Embedded artist",
                lrc_text="[00:01.00]Embedded lyric\n",
            )
            self.player.set_library([track])
            with patch(
                "player.MutagenFile",
                side_effect=[
                    SimpleNamespace(info=SimpleNamespace(length=60), tags={}),
                    SimpleNamespace(
                        info=None,
                        tags={
                            "title": ["Embedded title"],
                            "artist": ["Embedded artist"],
                        },
                    ),
                ],
            ):
                self.player.play_index(0)

            self.assertEqual(self.player.track_metadata["artist"], "Embedded artist")
            self.assertEqual(self.player.track_metadata["title"], "Embedded title")
            self.assertEqual(self.player.lyrics, [LyricLine(1.0, "Embedded lyric")])

    def test_shuffle_avoids_current_track_and_previous_uses_history(self) -> None:
        self.player.play_index(0)
        self.player.shuffle = True
        with patch("player.random.shuffle", side_effect=lambda tracks: None):
            self.player.next_track()

        self.assertEqual(self.player.current_index, 2)
        self.player.previous_track()
        self.assertEqual(self.player.current_index, 0)

    def test_shuffle_plays_every_other_track_once_before_repeating(self) -> None:
        self.player.set_library(
            [Path("first.mp3"), Path("second.mp3"), Path("third.mp3")]
        )
        self.player.play_index(0)
        self.player.shuffle = True

        played = [self.player.current_index]
        for _ in range(2):
            self.player.next_track()
            played.append(self.player.current_index)

        self.assertEqual(set(played), {0, 1, 2})
        self.player.next_track()
        self.assertNotEqual(self.player.current_index, played[-1])

    def test_seek_updates_position_and_can_pause(self) -> None:
        self.player.play_index(0)
        self.player.seek(35)

        self.assertEqual(self.player.position, 35)
        self.assertEqual(self.player.duration, 120)

        self.player.pause()
        self.assertTrue(self.player.is_paused)
        self.assertFalse(self.player.is_playing)

    def test_loads_case_insensitive_lrc_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "New Song.mp3"
            audio_path.touch()
            lyrics_path = Path(temporary_directory) / "new song.LRC"
            lyrics_path.write_text("[00:01.00]First line\n", encoding="utf-8")
            self.player.set_library([audio_path])

            self.player.play_index(0)

            self.assertEqual(self.player.lyrics, [LyricLine(1.0, "First line")])


if __name__ == "__main__":
    unittest.main()
