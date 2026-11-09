from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

import av
import lameenc
import yt_dlp


ProgressCallback = Callable[[dict[str, object]], None]


def _convert_to_mp3(source: Path, destination: Path) -> None:
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(192)
    encoder.set_in_sample_rate(44100)
    encoder.set_out_sample_rate(44100)
    encoder.set_channels(2)
    encoder.set_quality(2)
    resampler = av.AudioResampler(format="s16", layout="stereo", rate=44100)

    try:
        with av.open(str(source)) as input_file:
            audio_stream = next(
                (stream for stream in input_file.streams if stream.type == "audio"),
                None,
            )
            if audio_stream is None:
                raise RuntimeError("The downloaded file contains no audio stream.")

            with destination.open("wb") as output_file:
                for frame in input_file.decode(audio=audio_stream.index):
                    for pcm_frame in resampler.resample(frame):
                        pcm_size = pcm_frame.samples * len(pcm_frame.layout.channels) * 2
                        pcm_data = bytes(pcm_frame.planes[0])[:pcm_size]
                        output_file.write(encoder.encode(pcm_data))

                for pcm_frame in resampler.resample(None):
                    pcm_size = pcm_frame.samples * len(pcm_frame.layout.channels) * 2
                    pcm_data = bytes(pcm_frame.planes[0])[:pcm_size]
                    output_file.write(encoder.encode(pcm_data))

                output_file.write(encoder.flush())
    except Exception as error:
        destination.unlink(missing_ok=True)
        if isinstance(error, RuntimeError):
            raise
        raise RuntimeError(f"Could not convert downloaded audio to MP3: {error}") from error

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("The downloaded file did not produce any MP3 audio.")


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

        with tempfile.TemporaryDirectory(
            prefix=".tmusic-download-",
            dir=self.download_folder,
        ) as temporary_directory:
            options: dict[str, object] = {
                "format": "bestaudio/best",
                "outtmpl": str(Path(temporary_directory) / "%(title)s.%(ext)s"),
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
                        downloaded_path = str(downloader.prepare_filename(info))
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
            if not audio_path.is_file():
                raise RuntimeError(
                    f"Download finished, but the audio file was not found: {audio_path}"
                )

            mp3_path = self.download_folder / f"{audio_path.stem}.mp3"
            converted_path = Path(temporary_directory) / f"{audio_path.stem}.mp3"
            _convert_to_mp3(audio_path, converted_path)
            converted_path.replace(mp3_path)
            return mp3_path
