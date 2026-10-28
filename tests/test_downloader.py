import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import av
import yt_dlp

from downloader import Downloader, _convert_to_mp3


class DownloaderTests(unittest.TestCase):
    def test_download_reports_progress_and_returns_saved_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "track.webm"
            audio_path.touch()
            mp3_path = Path(temporary_directory) / "track.mp3"
            progress_updates: list[dict[str, object]] = []
            options_seen: dict[str, object] = {}
            youtube_dl = MagicMock()
            youtube_dl.__enter__.return_value.extract_info.return_value = {
                "filepath": str(audio_path)
            }

            def create_downloader(options):
                options_seen.update(options)
                return youtube_dl

            with patch("downloader.yt_dlp.YoutubeDL", side_effect=create_downloader):
                with patch(
                    "downloader._convert_to_mp3",
                    side_effect=lambda _source, destination: destination.touch(),
                ) as convert:
                    result = Downloader(temporary_directory).download_audio(
                        "https://example.com/watch?v=track",
                        progress_updates.append,
                    )
            options_seen["progress_hooks"][0](
                {"status": "downloading", "downloaded_bytes": 50}
            )

            self.assertEqual(result, mp3_path)
            convert.assert_called_once()
            self.assertEqual(convert.call_args.args[0], audio_path)
            self.assertEqual(convert.call_args.args[1].suffix, ".mp3")
            self.assertEqual(
                progress_updates,
                [{"status": "downloading", "downloaded_bytes": 50}],
            )
            self.assertTrue(options_seen["noplaylist"])
            self.assertNotIn("postprocessors", options_seen)

    def test_blank_url_is_rejected_without_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("downloader.yt_dlp.YoutubeDL") as youtube_dl:
                with self.assertRaisesRegex(ValueError, "Enter a video"):
                    Downloader(temporary_directory).download_audio(" ")
            youtube_dl.assert_not_called()

    def test_download_errors_are_reported_to_the_caller(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            youtube_dl = MagicMock()
            youtube_dl.__enter__.return_value.extract_info.side_effect = (
                yt_dlp.utils.DownloadError("source unavailable")
            )
            with patch("downloader.yt_dlp.YoutubeDL", return_value=youtube_dl):
                with self.assertRaisesRegex(RuntimeError, "source unavailable"):
                    Downloader(temporary_directory).download_audio(
                        "https://example.com/watch?v=missing"
                    )

    def test_bot_verification_error_explains_supported_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            youtube_dl = MagicMock()
            youtube_dl.__enter__.return_value.extract_info.side_effect = (
                yt_dlp.utils.DownloadError(
                    "Sign in to confirm you're not a bot."
                )
            )
            with patch("downloader.yt_dlp.YoutubeDL", return_value=youtube_dl):
                with self.assertRaisesRegex(
                    RuntimeError, "official download option"
                ) as error:
                    Downloader(temporary_directory).download_audio(
                        "https://example.com/watch?v=blocked"
                    )

            self.assertIn("anti-bot verification", str(error.exception))

    def test_lameenc_converts_decoded_audio_to_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "input.wav"
            destination = Path(temporary_directory) / "output.mp3"
            with wave.open(str(source), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(22050)
                sample_count = 22050
                samples = (
                    int(12000 * math.sin(2 * math.pi * 440 * index / 22050))
                    for index in range(sample_count)
                )
                audio_file.writeframes(
                    struct.pack(f"<{sample_count}h", *samples)
                )

            _convert_to_mp3(source, destination)

            self.assertGreater(destination.stat().st_size, 0)
            with av.open(str(destination), format="mp3") as mp3_file:
                decoded_frames = list(mp3_file.decode(audio=0))
            self.assertTrue(decoded_frames)


if __name__ == "__main__":
    unittest.main()
