from __future__ import annotations

import threading
from collections.abc import Callable


def _load_macos_api():
    try:
        import objc
        from Foundation import NSDate, NSRunLoop
        from MediaPlayer import (
            MPMediaItemPropertyAlbumTitle,
            MPMediaItemPropertyArtist,
            MPMediaItemPropertyPlaybackDuration,
            MPMediaItemPropertyTitle,
            MPNowPlayingInfoCenter,
            MPNowPlayingInfoPropertyElapsedPlaybackTime,
            MPNowPlayingInfoPropertyPlaybackRate,
            MPRemoteCommandCenter,
        )
    except ImportError as error:
        raise RuntimeError(
            "macOS media controls require the 'pyobjc-framework-MediaPlayer' package."
        ) from error

    try:
        from MediaPlayer import MPNowPlayingPlaybackState
    except ImportError:
        MPNowPlayingPlaybackState = None
    try:
        from MediaPlayer import MPRemoteCommandHandlerStatus
    except ImportError:
        MPRemoteCommandHandlerStatus = None

    return {
        "autorelease_pool": objc.autorelease_pool,
        "NSDate": NSDate,
        "NSRunLoop": NSRunLoop,
        "MPMediaItemPropertyAlbumTitle": MPMediaItemPropertyAlbumTitle,
        "MPMediaItemPropertyArtist": MPMediaItemPropertyArtist,
        "MPMediaItemPropertyPlaybackDuration": MPMediaItemPropertyPlaybackDuration,
        "MPMediaItemPropertyTitle": MPMediaItemPropertyTitle,
        "MPNowPlayingInfoCenter": MPNowPlayingInfoCenter,
        "MPNowPlayingInfoPropertyElapsedPlaybackTime": (
            MPNowPlayingInfoPropertyElapsedPlaybackTime
        ),
        "MPNowPlayingInfoPropertyPlaybackRate": (
            MPNowPlayingInfoPropertyPlaybackRate
        ),
        "MPRemoteCommandCenter": MPRemoteCommandCenter,
        "MPNowPlayingPlaybackState": MPNowPlayingPlaybackState,
        "MPRemoteCommandHandlerStatus": MPRemoteCommandHandlerStatus,
    }


class MacNowPlaying:
    """Publish playback state to the macOS Now Playing and remote command centers."""

    def __init__(
        self,
        player_controller,
        command_callback: Callable[[str, object | None], None],
    ) -> None:
        self.player = player_controller
        self.command_callback = command_callback
        self._stop = threading.Event()
        self._api: dict[str, object] = {}
        self._info_center = None
        self._targets: list[tuple[object, object]] = []
        self._last_signature: tuple[object, ...] | None = None

    def start(self) -> None:
        api = _load_macos_api()
        self._api = api
        self._info_center = api["MPNowPlayingInfoCenter"].defaultCenter()
        command_center = api["MPRemoteCommandCenter"].sharedCommandCenter()

        commands = (
            ("playCommand", "play"),
            ("pauseCommand", "pause"),
            ("togglePlayPauseCommand", "toggle"),
            ("stopCommand", "stop"),
            ("nextTrackCommand", "next"),
            ("previousTrackCommand", "previous"),
        )
        for selector, action in commands:
            command = getattr(command_center, selector)()
            command.setEnabled_(True)
            target = command.addTargetWithHandler_(
                self._make_handler(action)
            )
            self._targets.append((command, target))

        position_command = command_center.changePlaybackPositionCommand()
        position_command.setEnabled_(True)
        target = position_command.addTargetWithHandler_(
            self._make_position_handler()
        )
        self._targets.append((position_command, target))

        try:
            self._publish(force=True)
            run_loop = api["NSRunLoop"].currentRunLoop()
            autorelease_pool = api["autorelease_pool"]
            while not self._stop.is_set():
                with autorelease_pool():
                    self._publish()
                    run_loop.runUntilDate_(
                        api["NSDate"].dateWithTimeIntervalSinceNow_(0.5)
                    )
        finally:
            self._cleanup()

    def stop(self) -> None:
        self._stop.set()

    def _cleanup(self) -> None:
        for command, target in self._targets:
            try:
                command.removeTarget_(target)
            except Exception:
                pass
        self._targets.clear()
        try:
            self._info_center.setNowPlayingInfo_(None)
            self._set_playback_state("stopped")
        except Exception:
            pass

    def _success_status(self) -> int:
        status = self._api.get("MPRemoteCommandHandlerStatus")
        return int(getattr(status, "Success", 0)) if status is not None else 0

    def _make_handler(self, action: str):
        def handler(_event: object) -> int:
            if not self._stop.is_set():
                self.command_callback(action, None)
            return self._success_status()

        return handler

    def _make_position_handler(self):
        def handler(event: object) -> int:
            if not self._stop.is_set():
                position = float(getattr(event, "positionTime", 0.0) or 0.0)
                self.command_callback("seek", max(0.0, position))
            return self._success_status()

        return handler

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
            round(float(player.duration or 0.0), 1),
        )
        if force or signature != self._last_signature:
            self._publish_metadata(track, title, artist, album)
            self._set_playback_state(status)
            self._last_signature = signature
        self._publish_elapsed_time()

    def _publish_metadata(
        self,
        track,
        title: str,
        artist: str,
        album: str,
    ) -> None:
        if track is None:
            self._info_center.setNowPlayingInfo_(None)
            return
        api = self._api
        info: dict[str, object] = {
            api["MPMediaItemPropertyTitle"]: title,
            api["MPMediaItemPropertyArtist"]: artist,
            api["MPMediaItemPropertyAlbumTitle"]: album,
            api["MPNowPlayingInfoPropertyElapsedPlaybackTime"]: 0.0,
            api["MPNowPlayingInfoPropertyPlaybackRate"]: 0.0,
        }
        if self.player.duration is not None:
            info[api["MPMediaItemPropertyPlaybackDuration"]] = float(
                self.player.duration
            )
        self._info_center.setNowPlayingInfo_(info)

    def _publish_elapsed_time(self) -> None:
        if self.player.current_track is None:
            return
        api = self._api
        current_info = self._info_center.nowPlayingInfo()
        info = dict(current_info) if current_info is not None else {}
        info[api["MPNowPlayingInfoPropertyElapsedPlaybackTime"]] = float(
            self.player.position
        )
        info[api["MPNowPlayingInfoPropertyPlaybackRate"]] = (
            1.0 if self.player.is_playing else 0.0
        )
        self._info_center.setNowPlayingInfo_(info)

    def _set_playback_state(self, status: str) -> None:
        state_enum = self._api.get("MPNowPlayingPlaybackState")
        if state_enum is None:
            return
        state = {
            "playing": getattr(state_enum, "Playing", 1),
            "paused": getattr(state_enum, "Paused", 2),
            "stopped": getattr(state_enum, "Stopped", 3),
        }[status]
        try:
            self._info_center.setPlaybackState_(state)
        except Exception:
            pass


def create_service(
    player_controller,
    command_callback: Callable[[str, object | None], None],
) -> MacNowPlaying:
    return MacNowPlaying(player_controller, command_callback)


def start_service(
    player_controller,
    command_callback: Callable[[str, object | None], None],
) -> None:
    try:
        create_service(player_controller, command_callback).start()
    except Exception as error:
        raise RuntimeError(f"Could not start macOS media controls: {error}") from error
