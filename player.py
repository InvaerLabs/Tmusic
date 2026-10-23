from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

import pygame
from mutagen import File as MutagenFile, MutagenError
from mutagen.id3 import ID3, ID3NoHeaderError, SYLT, TIT2, TPE1, USLT


AUDIO_EXTENSIONS = {".flac", ".mp3", ".ogg", ".wav"}
_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_OFFSET = re.compile(r"\[offset:([+-]?\d+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class LyricLine:
    timestamp: float
    text: str


def parse_lrc(path: Path) -> list[LyricLine]:
    """Read timestamped LRC lines, including repeated timestamps and offsets."""
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_lrc_text(content)


def discover_tracks(folders: list[Path]) -> list[Path]:
    tracks: set[Path] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        tracks.update(
            path.resolve()
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        )
    return sorted(tracks, key=lambda path: path.name.casefold())


def format_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    total_seconds = int(seconds)
    return f"{total_seconds // 60:02}:{total_seconds % 60:02}"


def format_lrc(lyrics: list[LyricLine]) -> str:
    return "\n".join(
        f"[{int(line.timestamp) // 60:02}:{line.timestamp % 60:05.2f}]{line.text}"
        for line in lyrics
    )


def save_mp3_metadata(
    path: Path,
    *,
    title: str,
    artist: str,
    lrc_text: str,
) -> Path:
    if path.suffix.casefold() != ".mp3":
        raise ValueError("Metadata editing is currently supported for MP3 files only.")
    if not title.strip():
        raise ValueError("Track title cannot be empty.")

    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title.strip()).rstrip(" .")
    if not safe_title:
        raise ValueError("Choose a title that can be used as a file name.")
    if safe_title.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"(?:COM|LPT)[1-9]", safe_title, re.IGNORECASE
    ):
        safe_title = f"_{safe_title}"
    destination = path.with_name(f"{safe_title}.mp3")
    same_file = destination.exists() and os.path.samefile(destination, path)
    if destination.exists() and not same_file:
        raise FileExistsError(f"A file named {destination.name} already exists.")

    lyrics = parse_lrc_text(lrc_text)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    except (OSError, MutagenError) as error:
        raise RuntimeError(f"Could not read MP3 tags: {error}") from error
    tags.delall("TIT2")
    tags.delall("TPE1")
    tags.delall("USLT")
    tags.delall("SYLT")
    tags.add(TIT2(encoding=3, text=title.strip()))
    if artist.strip():
        tags.add(TPE1(encoding=3, text=artist.strip()))
    if lrc_text.strip():
        tags.add(
            USLT(
                encoding=3,
                lang="eng",
                desc="",
                text="\n".join(line.text for line in lyrics) if lyrics else lrc_text.strip(),
            )
        )
    if lyrics:
        tags.add(
            SYLT(
                encoding=3,
                lang="eng",
                format=2,
                type=1,
                desc="",
                text=[(line.text, round(line.timestamp * 1000)) for line in lyrics],
            )
        )
    try:
        tags.save(path, v2_version=3)
    except (OSError, MutagenError) as error:
        raise RuntimeError(f"Could not save MP3 tags: {error}") from error

    if destination != path and not same_file:
        path.rename(destination)
    return destination


def parse_lrc_text(content: str) -> list[LyricLine]:
    offset = 0.0
    lines: list[LyricLine] = []
    for raw_line in content.splitlines():
        offset_match = _OFFSET.search(raw_line)
        if offset_match:
            offset = int(offset_match.group(1)) / 1000
        timestamps = list(_TIMESTAMP.finditer(raw_line))
        if not timestamps:
            continue
        text = raw_line[timestamps[-1].end():].strip()
        for match in timestamps:
            minutes, seconds = int(match.group(1)), int(match.group(2))
            if seconds >= 60:
                continue
            fraction = match.group(3) or "0"
            timestamp = minutes * 60 + seconds + int(fraction) / 10 ** len(fraction)
            lines.append(LyricLine(max(0.0, timestamp + offset), text))
    return sorted(lines, key=lambda line: line.timestamp)


def read_track_lyrics(track: Path) -> tuple[list[LyricLine], bool]:
    sidecar = next(
        (
            candidate
            for candidate in track.parent.iterdir()
            if candidate.is_file()
            and candidate.stem.casefold() == track.stem.casefold()
            and candidate.suffix.casefold() == ".lrc"
        ),
        None,
    )
    if sidecar is not None:
        return parse_lrc(sidecar), True

    if track.suffix.casefold() != ".mp3":
        return [], False

    try:
        id3 = ID3(track)
    except (OSError, MutagenError, ID3NoHeaderError) as error:
        if isinstance(error, ID3NoHeaderError):
            return [], False
        raise RuntimeError(f"Could not read lyrics from {track.name}: {error}") from error

    synchronized: list[LyricLine] = []
    for frame in id3.getall("SYLT"):
        if getattr(frame, "format", None) != 2:
            continue
        for text, timestamp_ms in frame.text:
            synchronized.append(LyricLine(max(0.0, timestamp_ms / 1000), text))
    if synchronized:
        return sorted(synchronized, key=lambda line: line.timestamp), True

    unsynchronized = id3.getall("USLT")
    if unsynchronized:
        plain_text = next(
            (frame.text for frame in unsynchronized if frame.text.strip()),
            "",
        )
        if plain_text:
            return [
                LyricLine(0.0, line)
                for line in plain_text.splitlines()
                if line.strip()
            ], False
    return [], False


class MusicPlayer:
    """Small pygame-backed playback controller used by the Tk interface."""

    def __init__(self) -> None:
        self.tracks: list[Path] = []
        self.current_index: int | None = None
        self.current_track: Path | None = None
        self.track_metadata: dict[str, str] = {}
        self.lyrics: list[LyricLine] = []
        self.lyrics_synced = False
        self.duration: float | None = None
        self.volume = 0.72
        self._shuffle = False
        self.repeat_mode = "off"
        self.is_playing = False
        self.is_paused = False
        self._base_position = 0.0
        self._history: list[int] = []
        self._shuffle_remaining: list[int] = []
        self.audio_error: str | None = None

        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(self.volume)
        except pygame.error as error:
            self.audio_error = str(error)

    def set_library(self, tracks: list[Path]) -> None:
        self.tracks = tracks
        self._shuffle_remaining.clear()
        self._history.clear()
        if self.current_track in tracks:
            self.current_index = tracks.index(self.current_track)
        elif self.current_track is not None:
            self.stop()
            self.current_track = None
            self.track_metadata = {}
            self.current_index = None
            self.lyrics = []
            self.lyrics_synced = False
            self.duration = None

    def play_index(self, index: int) -> None:
        if self.audio_error:
            raise RuntimeError(f"Audio output could not be initialized: {self.audio_error}")
        if not 0 <= index < len(self.tracks):
            raise IndexError("Track selection is outside the library.")

        track = self.tracks[index]
        pygame.mixer.music.load(str(track))
        try:
            audio_metadata = MutagenFile(track)
            easy_metadata = MutagenFile(track, easy=True)
        except (OSError, MutagenError) as error:
            raise RuntimeError(f"Could not read track metadata: {error}") from error
        audio_info = getattr(audio_metadata, "info", None)
        audio_length = getattr(audio_info, "length", None)
        self.duration = float(audio_length) if audio_length else None
        self.track_metadata = {}
        if easy_metadata is not None and easy_metadata.tags is not None:
            for key in ("title", "artist", "album", "albumartist", "tracknumber", "date"):
                values = easy_metadata.tags.get(key)
                if values:
                    self.track_metadata[key] = str(values[0] if isinstance(values, list) else values)
        self.current_index = index
        self.current_track = track
        self._base_position = 0.0
        self.is_paused = False
        self.lyrics, self.lyrics_synced = read_track_lyrics(track)
        self.play()

    def play(self) -> None:
        if self.audio_error:
            raise RuntimeError(f"Audio output could not be initialized: {self.audio_error}")
        if self.current_track is None:
            if not self.tracks:
                return
            self.play_index(0)
            return
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
        else:
            if self.duration is not None and self._base_position >= self.duration:
                self._base_position = 0.0
            pygame.mixer.music.play(start=self._base_position)
        self.is_playing = True

    def pause(self) -> None:
        if self.is_playing:
            self._base_position = self.position
            pygame.mixer.music.pause()
            self.is_playing = False
            self.is_paused = True

    def toggle_play_pause(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        if not self.audio_error:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self._base_position = 0.0

    @property
    def position(self) -> float:
        if self.is_playing:
            elapsed = pygame.mixer.music.get_pos()
            if elapsed >= 0:
                return self._base_position + elapsed / 1000
        return self._base_position

    def seek(self, seconds: float) -> None:
        if self.current_track is None or self.audio_error:
            return
        upper_bound = self.duration if self.duration is not None else max(0.0, seconds)
        self._base_position = min(max(0.0, seconds), upper_bound)
        if self.is_playing:
            pygame.mixer.music.play(start=self._base_position)
        elif self.is_paused:
            pygame.mixer.music.play(start=self._base_position)
            pygame.mixer.music.pause()

    def set_volume(self, volume: float) -> None:
        self.volume = min(1.0, max(0.0, volume))
        if not self.audio_error:
            pygame.mixer.music.set_volume(self.volume)

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @shuffle.setter
    def shuffle(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self._shuffle:
            if hasattr(self, "_shuffle_remaining"):
                self._shuffle_remaining.clear()
                self._history.clear()
        self._shuffle = enabled

    def track_finished(self) -> bool:
        return self.is_playing and not pygame.mixer.music.get_busy()

    def next_track(self) -> None:
        if not self.tracks:
            return
        current = self.current_index if self.current_index is not None else -1
        if self.shuffle and len(self.tracks) > 1:
            self._history.append(current)
            if not self._shuffle_remaining:
                self._shuffle_remaining = [
                    index for index in range(len(self.tracks)) if index != current
                ]
                random.shuffle(self._shuffle_remaining)
            elif current in self._shuffle_remaining:
                self._shuffle_remaining.remove(current)
            next_index = self._shuffle_remaining.pop()
        else:
            self._shuffle_remaining.clear()
            next_index = (current + 1) % len(self.tracks)
        self.play_index(next_index)

    def previous_track(self) -> None:
        if not self.tracks:
            return
        if self.position > 3:
            self.seek(0)
            if self.is_paused:
                self.is_paused = False
                self.play()
            return

        if self.shuffle and self._history:
            previous = self._history.pop()
            if 0 <= previous < len(self.tracks):
                current = self.current_index
                if current is not None:
                    if current not in self._shuffle_remaining:
                        self._shuffle_remaining.append(current)
                self.play_index(previous)
                return

        current = self.current_index if self.current_index is not None else 0
        self.play_index((current - 1) % len(self.tracks))

    def load_lyrics(self, path: Path) -> list[LyricLine]:
        self.lyrics = parse_lrc(path)
        return self.lyrics

    def active_lyric_index(self) -> int | None:
        if not self.lyrics or not self.lyrics_synced:
            return None
        current = self.position
        active_index: int | None = None
        for index, line in enumerate(self.lyrics):
            if line.timestamp > current:
                break
            active_index = index
        return active_index

    def lyric_position(self, index: int) -> float:
        return self.lyrics[index].timestamp


def waveform_peaks(path: Path, width: int = 512) -> list[float]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []
    command = [
        ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "4000",
        "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Could not read audio waveform: {error}") from error

    samples = array("h")
    samples.frombytes(result.stdout[: len(result.stdout) - len(result.stdout) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return []

    peaks: list[float] = []
    for bucket in range(width):
        start = bucket * len(samples) // width
        end = max(start + 1, (bucket + 1) * len(samples) // width)
        if start >= len(samples):
            break
        peak = max(abs(sample) for sample in samples[start:min(end, len(samples))])
        peaks.append(peak / 32768)
    return peaks
