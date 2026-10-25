from __future__ import annotations

from pathlib import Path
from typing import Callable

import yt_dlp


ProgressCallback = Callable[[dict[str, object]], None]


class Downloader:
    def __init__(self, download_folder: str | Path = "downloads") -> None:
        self.download_folder = Path(download_folder).expanduser()
        self.download_folder.mkdir(parents=True, exist_ok=True)

    def download_audio(
        self,
        url: str,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        clean_url = url.strip()
        if not clean_url:
            raise ValueError("Enter a video or playlist URL.")

        def report_progress(data: dict[str, object]) -> None:
            if progress_callback is not None:
                progress_callback(data)

        options: dict[str, object] = {
            "format": "bestaudio/best",
            "outtmpl": str(self.download_folder / "%(title)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "progress_hooks": [report_progress],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(clean_url, download=True)
                if not isinstance(info, dict):
                    raise RuntimeError("The source did not return downloadable audio.")
                downloaded_path = info.get("filepath")
                if not downloaded_path:
                    requested_downloads = info.get("requested_downloads", [])
                    if requested_downloads:
                        downloaded_path = requested_downloads[0].get("filepath")
                if not downloaded_path:
                    prepared_path = Path(downloader.prepare_filename(info))
                    downloaded_path = str(prepared_path.with_suffix(".mp3"))
        except yt_dlp.utils.DownloadError as error:
            message = str(error)
            normalized_message = message.casefold().replace("’", "'")
            if (
                "sign in to confirm" in normalized_message
                or "confirm you're not a bot" in normalized_message
                or "confirm you are not a bot" in normalized_message
            ):
                raise RuntimeError(
                    "This service requires sign-in or anti-bot verification, which "
                    "Tmusic can't complete. Use the service's official download "
                    "option, or choose a direct download you have permission to use."
                ) from error
            raise RuntimeError(f"Download failed: {error}") from error

        audio_path = Path(downloaded_path).expanduser()
        converted_path = audio_path.with_suffix(".mp3")
        if audio_path.suffix.lower() != ".mp3" and converted_path.is_file():
            audio_path = converted_path
        if not audio_path.is_file():
            raise RuntimeError(f"Download finished, but the audio file was not found: {audio_path}")
        return audio_path
