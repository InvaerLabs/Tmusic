import unittest
from pathlib import Path
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
