from __future__ import annotations

import importlib
import threading
from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace

BUTTON_ACTIONS = {
    "play": ("play", None),
    "pause": ("pause", None),
    "play_pause": ("toggle", None),
    "stop": ("stop", None),
    "next": ("next", None),
    "previous": ("previous", None),
    "fast_forward": ("seek_by", 10.0),
    "rewind": ("seek_by", -10.0),
}


def _load_windows_api() -> SimpleNamespace:
    """Load the Windows Runtime projection from winsdk or winrt."""
    last_error: Exception | None = None
    for package in ("winsdk", "winrt"):
        try:
            sdk = importlib.import_module(package)
            media = importlib.import_module(f"{package}.windows.media")
            playback = importlib.import_module(
                f"{package}.windows.media.playback"
            )
        except ImportError as error:
            last_error = error
            continue
        return SimpleNamespace(
            sdk=sdk,
            MediaPlayer=playback.MediaPlayer,
            MediaPlaybackStatus=media.MediaPlaybackStatus,
            MediaPlaybackType=media.MediaPlaybackType,
            SystemMediaTransportControlsTimelineProperties=(
                media.SystemMediaTransportControlsTimelineProperties
            ),
        )
    raise RuntimeError(
        "Windows media controls require the 'winsdk' package or a compatible "
        "'winrt' projection."
    ) from last_error


def _seconds(value: object) -> float:
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


class WindowsMediaControls:
    """Expose playback through the Windows System Media Transport Controls."""

    def __init__(
        self,
        player_controller,
        command_callback: Callable[[str, object | None], None],
    ) -> None:
        self.player = player_controller
        self.command_callback = command_callback
        self._stop = threading.Event()
        self._api: SimpleNamespace | None = None
        self._smtc = None
        self._updater = None
        self._media_player = None
        self._last_signature: tuple[object, ...] | None = None

    def start(self) -> None:
        api = _load_windows_api()
        self._api = api
        try:
            init_apartment = getattr(api.sdk, "init_apartment", None)
            if init_apartment is not None:
                init_apartment()
        except Exception:
            pass

        self._media_player = api.MediaPlayer()
        command_manager = getattr(self._media_player, "command_manager", None)
        if command_manager is not None:
            command_manager.is_enabled = False

        self._smtc = self._media_player.system_media_transport_controls
        self._smtc.is_enabled = True
        self._smtc.add_button_pressed(self._on_button_pressed)
        add_position_handler = getattr(
            self._smtc, "add_playback_position_change_requested", None
        )
        if add_position_handler is not None:
            add_position_handler(self._on_position_change_requested)
        self._updater = self._smtc.display_updater
        self._updater.type = api.MediaPlaybackType.MUSIC

        try:
            self._publish(force=True)
            while not self._stop.wait(0.5):
                self._publish()
        finally:
            self._cleanup()

    def stop(self) -> None:
        self._stop.set()

    def _cleanup(self) -> None:
        try:
            self._smtc.is_enabled = False
        except Exception:
            pass
        try:
            self._updater.clear()
        except Exception:
            pass
        try:
            self._media_player.close()
        except Exception:
            pass

    def _on_button_pressed(self, _sender: object, args: object) -> None:
        if self._stop.is_set():
            return
        button = getattr(args, "button", None)
        name = getattr(button, "name", None) or str(button).rsplit(".", 1)[-1]
        action, value = BUTTON_ACTIONS.get(name.lower(), (None, None))
        if action is None:
            return
        if action == "seek_by":
            target = max(0.0, self.player.position + float(value or 0))
            self.command_callback("seek", target)
        else:
            self.command_callback(action, None)

    def _on_position_change_requested(self, _sender: object, args: object) -> None:
        if self._stop.is_set():
            return
        position = _seconds(getattr(args, "requested_playback_position", 0))
        self.command_callback("seek", max(0.0, position))

    def _publish(self, *, force: bool = False) -> None:
        player = self.player
        track = player.current_track
        metadata = player.track_metadata
        title = metadata.get("title", track.stem) if track is not None else ""
        artist = metadata.get("artist", "") if track is not None else ""
        album = metadata.get("album", "") if track is not None else ""
        status = (
            "playing"
            if player.is_playing
            else "paused" if player.is_paused else "stopped"
        )
        signature = (
            str(track) if track is not None else None,
            status,
            title,
            artist,
            album,
            bool(player.shuffle),
        )
        if force or signature != self._last_signature:
            self._publish_metadata(track, title, artist, album)
            self._publish_status(status, track is not None)
            self._last_signature = signature
        self._publish_timeline()

    def _publish_metadata(
        self,
        track,
        title: str,
        artist: str,
        album: str,
    ) -> None:
        updater = self._updater
        if track is None:
            updater.clear()
            return
        properties = updater.music_properties
        properties.title = title
        properties.artist = artist
        properties.album_title = album
        updater.type = self._api.MediaPlaybackType.MUSIC
        updater.update()

    def _publish_status(self, status: str, has_track: bool) -> None:
        api = self._api
        states = api.MediaPlaybackStatus
        self._smtc.playback_status = {
            "playing": states.PLAYING,
            "paused": states.PAUSED,
            "stopped": states.STOPPED if has_track else states.CLOSED,
        }[status]
        has_tracks = bool(self.player.tracks)
        self._smtc.is_play_enabled = has_tracks
        self._smtc.is_pause_enabled = has_track
        self._smtc.is_stop_enabled = has_track
        self._smtc.is_next_enabled = has_tracks
        self._smtc.is_previous_enabled = has_tracks
        self._smtc.is_fast_forward_enabled = has_track
        self._smtc.is_rewind_enabled = has_track

    def _publish_timeline(self) -> None:
        duration = self.player.duration
        if duration is None or duration <= 0:
            return
        timeline = self._api.SystemMediaTransportControlsTimelineProperties()
        timeline.start_time = timedelta(0)
        timeline.end_time = timedelta(seconds=duration)
        timeline.position = timedelta(
            seconds=min(max(self.player.position, 0.0), duration)
        )
        timeline.min_seek_time = timedelta(0)
        timeline.max_seek_time = timedelta(seconds=duration)
        self._smtc.update_timeline_properties(timeline)


def create_service(
    player_controller,
    command_callback: Callable[[str, object | None], None],
) -> WindowsMediaControls:
    return WindowsMediaControls(player_controller, command_callback)


def start_service(
    player_controller,
    command_callback: Callable[[str, object | None], None],
) -> None:
    try:
        create_service(player_controller, command_callback).start()
    except Exception as error:
        raise RuntimeError(f"Could not start Windows media controls: {error}") from error
