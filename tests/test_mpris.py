import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from player import LyricLine

try:
    from MPRIS import MediaPlayerMPRIS
except ImportError:
    MediaPlayerMPRIS = None


@unittest.skipIf(MediaPlayerMPRIS is None, "MPRIS system bindings are not installed")
class MprisPropertyTests(unittest.TestCase):
    def test_exposes_track_metadata_and_current_playback_properties(self) -> None:
        service = object.__new__(MediaPlayerMPRIS)
        service.player = SimpleNamespace(
            current_track=Path("/music/song.mp3"),
            current_index=0,
            lyrics=[LyricLine(1.0, "First lyric"), LyricLine(2.0, "Second lyric")],
            track_metadata={
                "title": "Song title",
                "artist": "Artist name",
                "album": "Album name",
            },
            duration=120.0,
            is_playing=True,
            is_paused=False,
            repeat_mode="all",
            shuffle=True,
            volume=0.5,
            position=12.0,
            tracks=[Path("/music/song.mp3")],
        )

        properties = service._player_properties()
        metadata = properties["Metadata"]

        self.assertEqual(str(properties["PlaybackStatus"]), "Playing")
        self.assertEqual(str(properties["LoopStatus"]), "Playlist")
        self.assertTrue(properties["Shuffle"])
        self.assertEqual(str(metadata["xesam:title"]), "Song title")
        self.assertEqual(list(metadata["xesam:artist"]), ["Artist name"])
        self.assertEqual(metadata["mpris:length"], 120_000_000)
        self.assertEqual(str(metadata["mpris:trackid"]), "/org/mpris/MediaPlayer2/Track/0")
        self.assertEqual(str(metadata["xesam:asText"]), "First lyric\nSecond lyric")

    def test_seek_signal_waits_until_requested_position_is_applied(self) -> None:
        service = object.__new__(MediaPlayerMPRIS)
        service.player = SimpleNamespace(position=0.0)
        service._stop_requested = threading.Event()
        service._seek_generation = 2
        service._seek_attempts = 0
        with patch.object(service, "Seeked") as seeked:
            self.assertTrue(service._seek_applied(2, 20.0))
            seeked.assert_not_called()
            service.player.position = 20.0
            self.assertFalse(service._seek_applied(2, 20.0))
            seeked.assert_called_once_with(20_000_000)

    def test_stopped_seek_watcher_does_not_emit_signal(self) -> None:
        service = object.__new__(MediaPlayerMPRIS)
        service.player = SimpleNamespace(position=20.0)
        service._stop_requested = threading.Event()
        service._stop_requested.set()
        service._seek_generation = 2
        service._seek_attempts = 0
        with patch.object(service, "Seeked") as seeked:
            self.assertFalse(service._seek_applied(2, 20.0))
            seeked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
