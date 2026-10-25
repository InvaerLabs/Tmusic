import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yt_dlp

from downloader import Downloader


class DownloaderTests(unittest.TestCase):
    def test_download_reports_progress_and_returns_saved_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio_path = Path(temporary_directory) / "track.mp3"
            audio_path.touch()
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
                result = Downloader(temporary_directory).download_audio(
                    "https://example.com/watch?v=track",
                    progress_updates.append,
                )
            options_seen["progress_hooks"][0](
                {"status": "downloading", "downloaded_bytes": 50}
            )

            self.assertEqual(result, audio_path)
            self.assertEqual(
                progress_updates,
                [{"status": "downloading", "downloaded_bytes": 50}],
            )
            self.assertTrue(options_seen["noplaylist"])
            self.assertEqual(
                options_seen["postprocessors"][0]["preferredcodec"],
                "mp3",
            )

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


if __name__ == "__main__":
    unittest.main()
