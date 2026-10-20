from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

import pygame
from mutagen import File as MutagenFile, MutagenError


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
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            if seconds >= 60:
                continue
            fraction = match.group(3) or "0"
            timestamp = minutes * 60 + seconds + int(fraction) / (10 ** len(fraction))
            lines.append(LyricLine(max(0.0, timestamp + offset), text))

    return sorted(lines, key=lambda line: line.timestamp)


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


class MusicPlayer:
    """Small pygame-backed playback controller used by the Tk interface."""

    def __init__(self) -> None:
        self.tracks: list[Path] = []
        self.current_index: int | None = None
        self.current_track: Path | None = None
        self.track_metadata: dict[str, str] = {}
        self.lyrics: list[LyricLine] = []
        self.duration: float | None = None
        self.volume = 0.72
        self.shuffle = False
        self.repeat_mode = "off"
        self.is_playing = False
        self.is_paused = False
        self._base_position = 0.0
        self._history: list[int] = []
        self.audio_error: str | None = None

        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(self.volume)
        except pygame.error as error:
            self.audio_error = str(error)

    def set_library(self, tracks: list[Path]) -> None:
        self.tracks = tracks
        if self.current_track in tracks:
            self.current_index = tracks.index(self.current_track)
        elif self.current_track is not None:
            self.stop()
            self.current_track = None
            self.track_metadata = {}
            self.current_index = None
            self.lyrics = []
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
        self.lyrics = self._lyrics_for(track)
        self.play()

    def _lyrics_for(self, track: Path) -> list[LyricLine]:
        sidecar = track.with_suffix(".lrc")
        if not sidecar.is_file():
            sidecar = next(
                (
                    candidate
                    for candidate in track.parent.iterdir()
                    if candidate.is_file()
                    and candidate.stem.casefold() == track.stem.casefold()
                    and candidate.suffix.casefold() == ".lrc"
                ),
                sidecar,
            )
        if sidecar.is_file():
            return parse_lrc(sidecar)
        return []

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

    def track_finished(self) -> bool:
        return self.is_playing and not pygame.mixer.music.get_busy()

    def next_track(self) -> None:
        if not self.tracks:
            return
        current = self.current_index if self.current_index is not None else -1
        if self.shuffle and len(self.tracks) > 1:
            self._history.append(current)
            candidates = [index for index in range(len(self.tracks)) if index != current]
            next_index = random.choice(candidates)
        else:
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
                self.play_index(previous)
                return

        current = self.current_index if self.current_index is not None else 0
        self.play_index((current - 1) % len(self.tracks))

    def load_lyrics(self, path: Path) -> list[LyricLine]:
        self.lyrics = parse_lrc(path)
        return self.lyrics

    def active_lyric_index(self) -> int | None:
        if not self.lyrics:
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
