"""Linux MPRIS 2.2 media-control endpoint for Tmusic."""

from __future__ import annotations

import threading
from collections.abc import Callable

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
ROOT_INTERFACE = "org.mpris.MediaPlayer2"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
NO_TRACK = dbus.ObjectPath("/org/mpris/MediaPlayer2/TrackList/NoTrack")
POLL_INTERVAL_MS = 500


class MediaPlayerMPRIS(dbus.service.Object):
    """MPRIS 2.2 endpoint; desktop commands are marshalled to Tk's event loop."""

    def __init__(
        self,
        player_controller,
        command_callback: Callable[[str, object | None], None],
    ) -> None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus_name = dbus.service.BusName(
            "org.mpris.MediaPlayer2.Tmusic",
            dbus.SessionBus(),
            allow_replacement=True,
            replace_existing=True,
            do_not_queue=True,
        )
        super().__init__(self.bus_name, OBJECT_PATH)
        self.player = player_controller
        self.command_callback = command_callback
        self.loop = GLib.MainLoop()
        self._stop_requested = threading.Event()
        self._seek_generation = 0
        self._seek_attempts = 0
        self._last_properties = self._player_properties()
        GLib.timeout_add(POLL_INTERVAL_MS, self._poll_properties)
        GLib.timeout_add(100, self._check_stop)

    @dbus.service.method(PLAYER_INTERFACE, in_signature="", out_signature="")
    def PlayPause(self) -> None:
        self._dispatch("toggle")

    @dbus.service.method(PLAYER_INTERFACE, in_signature="", out_signature="")
    def Play(self) -> None:
        self._dispatch("play")

    @dbus.service.method(PLAYER_INTERFACE, in_signature="", out_signature="")
    def Pause(self) -> None:
        self._dispatch("pause")

    @dbus.service.method(PLAYER_INTERFACE, in_signature="", out_signature="")
    def Stop(self) -> None:
        self._dispatch("stop")

    @dbus.service.method(PLAYER_INTERFACE, in_signature="", out_signature="")
    def Next(self) -> None:
        self._dispatch("next")

    @dbus.service.method(PLAYER_INTERFACE, in_signature="", out_signature="")
    def Previous(self) -> None:
        self._dispatch("previous")

    @dbus.service.method(PLAYER_INTERFACE, in_signature="x", out_signature="")
    def Seek(self, offset: int) -> None:
        target = self.player.position + int(offset) / 1_000_000
        if self.player.duration is not None:
            target = min(target, self.player.duration)
        target = max(0.0, target)
        self._dispatch("seek", target)
        self._watch_seek(target)

    @dbus.service.method(PLAYER_INTERFACE, in_signature="ox", out_signature="")
    def SetPosition(self, track_id: str, position: int) -> None:
        if str(track_id) != str(self._track_id()):
            return
        target = int(position) / 1_000_000
        if self.player.duration is not None:
            target = min(target, self.player.duration)
        target = max(0.0, target)
        self._dispatch("seek", target)
        self._watch_seek(target)

    def _watch_seek(self, target: float) -> None:
        self._seek_generation += 1
        self._seek_attempts = 0
        GLib.timeout_add(50, self._seek_applied, self._seek_generation, target)

    def _seek_applied(
        self,
        generation: int,
        target: float,
    ) -> bool:
        if self._stop_requested.is_set() or generation != self._seek_generation:
            return False
        self._seek_attempts += 1
        position = self.player.position
        if abs(position - target) <= 0.5:
            self.Seeked(round(position * 1_000_000))
            return False
        if self._seek_attempts >= 40:
            return False
        return True

    @dbus.service.signal(PLAYER_INTERFACE, signature="x")
    def Seeked(self, position: int) -> None:
        return

    @dbus.service.method(ROOT_INTERFACE, in_signature="", out_signature="")
    def Raise(self) -> None:
        self._dispatch("raise")

    @dbus.service.method(ROOT_INTERFACE, in_signature="", out_signature="")
    def Quit(self) -> None:
        self._dispatch("quit")

    @dbus.service.method(PROPERTIES_INTERFACE, in_signature="ss", out_signature="v")
    def Get(self, interface_name: str, property_name: str):
        properties = self.GetAll(interface_name)
        try:
            return properties[property_name]
        except KeyError as error:
            raise dbus.exceptions.DBusException(
                f"Unknown property {property_name!r} on {interface_name!r}",
                name="org.freedesktop.DBus.Error.UnknownProperty",
            ) from error

    @dbus.service.method(PROPERTIES_INTERFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface_name: str):
        if interface_name == PLAYER_INTERFACE:
            return dbus.Dictionary(self._player_properties(), signature="sv")
        if interface_name == ROOT_INTERFACE:
            return dbus.Dictionary(
                {
                    "CanQuit": dbus.Boolean(True),
                    "CanRaise": dbus.Boolean(True),
                    "Fullscreen": dbus.Boolean(False),
                    "CanSetFullscreen": dbus.Boolean(False),
                    "HasTrackList": dbus.Boolean(False),
                    "Identity": dbus.String("Tmusic"),
                    "DesktopEntry": dbus.String("tmusic"),
                    "SupportedUriSchemes": dbus.Array([], signature="s"),
                    "SupportedMimeTypes": dbus.Array(
                        ["audio/mpeg", "audio/flac", "audio/ogg", "audio/wav"],
                        signature="s",
                    ),
                },
                signature="sv",
            )
        return dbus.Dictionary({}, signature="sv")

    @dbus.service.method(PROPERTIES_INTERFACE, in_signature="ssv", out_signature="")
    def Set(self, interface_name: str, property_name: str, value) -> None:
        if interface_name != PLAYER_INTERFACE:
            self._property_error(property_name, "Properties on this interface are read-only.")
        if property_name == "Shuffle":
            self._dispatch("shuffle", bool(value))
        elif property_name == "Volume":
            volume = float(value)
            if not 0 <= volume <= 1:
                self._property_error(property_name, "Volume must be between 0.0 and 1.0.")
            self._dispatch("volume", volume)
        elif property_name == "LoopStatus":
            loop_status = str(value)
            loop_modes = {"None": "off", "Playlist": "all", "Track": "one"}
            if loop_status not in loop_modes:
                self._property_error(property_name, "LoopStatus must be None, Playlist, or Track.")
            self._dispatch("repeat", loop_modes[loop_status])
        else:
            self._property_error(property_name, "This property is read-only or unsupported.")

    @dbus.service.signal(PROPERTIES_INTERFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties) -> None:
        return

    def _property_error(self, property_name: str, message: str) -> None:
        raise dbus.exceptions.DBusException(
            f"Cannot set {property_name}: {message}",
            name="org.freedesktop.DBus.Error.PropertyReadOnly",
        )

    def _dispatch(self, action: str, value: object | None = None) -> None:
        self.command_callback(action, value)

    def _track_id(self) -> dbus.ObjectPath:
        if self.player.current_index is None:
            return NO_TRACK
        return dbus.ObjectPath(
            f"/org/mpris/MediaPlayer2/Track/{self.player.current_index}"
        )

    def _player_properties(self) -> dict[str, object]:
        track = self.player.current_track
        track_metadata = self.player.track_metadata
        metadata: dict[str, object] = {"mpris:trackid": self._track_id()}
        if track is not None:
            metadata.update(
                {
                    "xesam:title": dbus.String(
                        track_metadata.get("title", track.stem)
                    ),
                    "xesam:artist": dbus.Array(
                        [track_metadata["artist"]] if track_metadata.get("artist") else [],
                        signature="s",
                    ),
                    "xesam:album": dbus.String(track_metadata.get("album", "")),
                    "xesam:url": dbus.String(track.as_uri()),
                }
            )
            if self.player.lyrics:
                metadata["xesam:asText"] = dbus.String(
                    "\n".join(line.text for line in self.player.lyrics)
                )
            if self.player.duration is not None:
                metadata["mpris:length"] = dbus.Int64(
                    round(self.player.duration * 1_000_000)
                )

        repeat_status = {
            "off": "None",
            "all": "Playlist",
            "one": "Track",
        }.get(self.player.repeat_mode, "None")
        return {
            "PlaybackStatus": dbus.String(
                "Playing"
                if self.player.is_playing
                else "Paused" if self.player.is_paused else "Stopped"
            ),
            "LoopStatus": dbus.String(repeat_status),
            "Rate": dbus.Double(1.0),
            "Shuffle": dbus.Boolean(self.player.shuffle),
            "Metadata": dbus.Dictionary(metadata, signature="sv"),
            "Volume": dbus.Double(self.player.volume),
            "Position": dbus.Int64(round(self.player.position * 1_000_000)),
            "MinimumRate": dbus.Double(1.0),
            "MaximumRate": dbus.Double(1.0),
            "CanGoNext": dbus.Boolean(bool(self.player.tracks)),
            "CanGoPrevious": dbus.Boolean(bool(self.player.tracks)),
            "CanPlay": dbus.Boolean(bool(self.player.tracks)),
            "CanPause": dbus.Boolean(self.player.current_track is not None),
            "CanSeek": dbus.Boolean(
                self.player.current_track is not None and self.player.duration is not None
            ),
            "CanControl": dbus.Boolean(True),
        }

    def _poll_properties(self) -> bool:
        if self._stop_requested.is_set():
            return False
        current = self._player_properties()
        changed = {
            key: value
            for key, value in current.items()
            if key != "Position" and value != self._last_properties.get(key)
        }
        if changed:
            self.PropertiesChanged(PLAYER_INTERFACE, dbus.Dictionary(changed, signature="sv"), [])
        self._last_properties = current
        return True

    def _check_stop(self) -> bool:
        if not self._stop_requested.is_set():
            return True
        self.loop.quit()
        return False

    def stop(self) -> None:
        self._stop_requested.set()

    def start(self) -> None:
        try:
            self.loop.run()
        finally:
            try:
                self.remove_from_connection()
            finally:
                self.bus_name.release()


def create_service(
    player_controller,
    command_callback: Callable[[str, object | None], None],
) -> MediaPlayerMPRIS:
    return MediaPlayerMPRIS(player_controller, command_callback)


def start_service(
    player_controller,
    command_callback: Callable[[str, object | None], None],
) -> None:
    try:
        create_service(player_controller, command_callback).start()
    except (dbus.DBusException, GLib.Error) as error:
        raise RuntimeError(f"Could not start the MPRIS service: {error}") from error
