from __future__ import annotations

import base64
import hmac
import importlib
import json
import platform
import queue
import re
import secrets
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

from core.player import (
    MusicPlayer,
    discover_tracks,
    read_cover_art,
    read_track_lyrics,
    save_mp3_metadata,
)
from utils.preferences import (
    load_download_directory,
    load_mp3_bitrate,
    load_music_folders,
    load_theme_preference,
    save_download_directory,
    save_mp3_bitrate,
    save_music_folders,
    save_theme_preference,
    system_theme,
)
from utils.resources import resource_path

APP_VERSION = "3.0"
BITRATES = (192, 256, 320)

REMOTE_METHODS = frozenset(
    {
        "get_state",
        "add_music_folder",
        "remove_music_folder",
        "set_download_folder",
        "set_bitrate",
        "set_theme",
        "get_editor_data",
        "get_cover_preview",
        "ui_closed",
        "save_editor",
        "refresh_library",
        "play_track",
        "toggle_play",
        "play",
        "pause",
        "stop",
        "next_track",
        "previous_track",
        "seek",
        "set_volume",
        "set_shuffle",
        "set_repeat",
        "start_download",
        "cancel_download",
        "check_for_updates",
        "open_release",
    }
)


class _CoreHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], bridge: TmusicBridge, token: str):
        self.bridge = bridge
        self.token = token
        super().__init__(address, _CoreRequestHandler)


class _CoreRequestHandler(BaseHTTPRequestHandler):
    server: _CoreHTTPServer
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        authorized = hmac.compare_digest(
            self.headers.get("X-Tmusic-Token", ""),
            self.server.token,
        )
        if (
            self.client_address[0] != "127.0.0.1"
            or self.path != "/api"
            or not authorized
        ):
            payload = b'{"error":"Unauthorized local request."}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16 * 1024 * 1024:
                raise ValueError("Invalid request size.")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("Invalid core request.")
            method = request.get("method")
            args = request.get("args")
            if method not in REMOTE_METHODS or not isinstance(args, list):
                raise ValueError("Unsupported core request.")
            result = getattr(self.server.bridge, method)(*args)
            response = {"result": result}
            status = 200
        except (OSError, RuntimeError, TypeError, ValueError, IndexError, KeyError) as error:
            response = {"error": str(error)}
            status = 400
        payload = json.dumps(response, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _CoreClient:
    def __init__(self, host: str, port: int, token: str) -> None:
        self.url = f"http://{host}:{port}/api"
        self.token = token

    def call(self, method: str, *args: object) -> Any:
        if method not in REMOTE_METHODS:
            raise ValueError("Unsupported core request.")
        payload = json.dumps({"method": method, "args": args}).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Tmusic-Token": self.token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            result = json.loads(error.read().decode("utf-8"))
        if "error" in result:
            raise RuntimeError(result["error"])
        return result.get("result")


class _WebViewAPI:
    def __init__(self, client: _CoreClient) -> None:
        self._client = client
        self.window: Any = None
        self._window_x = 0
        self._window_y = 0
        self._drag_origin = (0, 0)
        self._initial_state = True
        self._close_approved = False

    def attach_window(self, window: Any, x: int, y: int) -> None:
        self.window = window
        self._window_x = x
        self._window_y = y
        self._drag_origin = (x, y)

    def get_state(self) -> dict[str, object]:
        state = self._client.call("get_state", self._initial_state)
        self._initial_state = False
        return state

    def refresh_library(self) -> None:
        self._client.call("refresh_library")

    def play_track(self, path: str) -> bool:
        return self._client.call("play_track", path)

    def toggle_play(self) -> None:
        self._client.call("toggle_play")

    def play(self) -> None:
        self._client.call("play")

    def pause(self) -> None:
        self._client.call("pause")

    def stop(self) -> None:
        self._client.call("stop")

    def next_track(self) -> None:
        self._client.call("next_track")

    def previous_track(self) -> None:
        self._client.call("previous_track")

    def seek(self, seconds: object) -> None:
        self._client.call("seek", seconds)

    def set_volume(self, value: object) -> None:
        self._client.call("set_volume", value)

    def set_shuffle(self, enabled: object) -> None:
        self._client.call("set_shuffle", enabled)

    def set_repeat(self, mode: str) -> None:
        self._client.call("set_repeat", mode)

    def choose_music_folder(self) -> str | None:
        import webview

        selected = self._dialog(webview.FileDialog.FOLDER, directory=str(Path.home()))
        return self._client.call("add_music_folder", selected) if selected else None

    def remove_music_folder(self, folder: str) -> None:
        self._client.call("remove_music_folder", folder)

    def choose_download_folder(self) -> str | None:
        import webview

        state = self.get_state()
        selected = self._dialog(
            webview.FileDialog.FOLDER,
            directory=state["downloadDirectory"],
        )
        return self._client.call("set_download_folder", selected) if selected else None

    def set_bitrate(self, value: object) -> None:
        self._client.call("set_bitrate", value)

    def set_theme(self, theme: str) -> None:
        self._client.call("set_theme", theme)

    def get_editor_data(self, path: str) -> dict[str, object]:
        return self._client.call("get_editor_data", path)

    def choose_cover(self) -> dict[str, str] | None:
        import webview

        selected = self._dialog(
            webview.FileDialog.OPEN,
            directory=str(Path.home()),
            file_types=["Image files (*.jpg;*.jpeg;*.png;*.gif;*.webp)"],
        )
        return self._client.call("get_cover_preview", selected) if selected else None

    def choose_lyrics(self) -> str | None:
        import webview

        selected = self._dialog(
            webview.FileDialog.OPEN,
            directory=str(Path.home()),
            file_types=("Lyrics files (*.lrc;*.txt)",),
        )
        return Path(selected).read_text(encoding="utf-8-sig") if selected else None

    def save_editor(
        self,
        path: str,
        title: str,
        artist: str,
        lyrics: str,
        cover_path: str | None,
    ) -> str:
        return self._client.call(
            "save_editor",
            path,
            title,
            artist,
            lyrics,
            cover_path,
        )

    def start_download(self, url: str) -> bool:
        return self._client.call("start_download", url)

    def cancel_download(self) -> None:
        self._client.call("cancel_download")

    def check_for_updates(self) -> None:
        self._client.call("check_for_updates")

    def open_release(self, url: str) -> bool:
        return self._client.call("open_release", url)

    def hide_window(self) -> None:
        self._close_window()

    def close(self) -> None:
        self._close_window()

    def begin_window_drag(self) -> None:
        self._drag_origin = (self._window_x, self._window_y)

    def move_window_drag(self, delta_x: object, delta_y: object) -> None:
        if self.window is None:
            return
        try:
            x = self._drag_origin[0] + round(float(delta_x))
            y = self._drag_origin[1] + round(float(delta_y))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid window position: {error}") from error
        self.window.move(x, y)
        self._window_x, self._window_y = x, y

    def on_window_closing(self) -> bool:
        if self._close_approved:
            return True
        state = self.get_state()
        download = state.get("download")
        if isinstance(download, dict) and download.get("active"):
            confirmed = self.window.create_confirmation_dialog(
                "Download in progress",
                "Closing Tmusic will cancel the active download. Continue?",
            )
            if not confirmed:
                return False
            self.cancel_download()
        return True

    def on_window_closed(self) -> None:
        try:
            self._client.call("ui_closed")
        except (OSError, RuntimeError, ValueError):
            return

    def _close_window(self) -> None:
        if self.window is not None:
            self._close_approved = True
            self.window.destroy()

    def _dialog(self, dialog_type: object, **kwargs: object) -> str | None:
        if self.window is None:
            raise RuntimeError("The application window is not available.")
        selected = self.window.create_file_dialog(dialog_type, **kwargs)
        if isinstance(selected, (list, tuple)):
            return str(selected[0]) if selected else None
        return str(selected) if selected else None


class TmusicBridge:
    def __init__(self) -> None:
        self.player = MusicPlayer()
        self._lock = threading.RLock()
        self._commands: queue.SimpleQueue[tuple[str, object | None]] = queue.SimpleQueue()
        self._command_thread: threading.Thread | None = None
        self._download_cancel = threading.Event()
        self._download_thread: threading.Thread | None = None
        self._download_progress: dict[str, object] = {}
        self._download_error: str | None = None
        self._download_finished: str | None = None
        self._download_active = False
        self._update_result: dict[str, str] | None = None
        self._update_checking = False
        self._service: Any = None
        self._service_thread: threading.Thread | None = None
        self._tray_icon: Any = None
        self._ui_process: subprocess.Popen[bytes] | None = None
        self._ui_lock = threading.Lock()
        self._ipc_server: _CoreHTTPServer | None = None
        self._ipc_thread: threading.Thread | None = None
        self._ipc_token = secrets.token_urlsafe(32)
        self._shutdown = threading.Event()
        self._closed = False
        self._last_error: str | None = None
        self._last_status = "Ready"
        self._library_revision = 0
        self._track_payload_key: tuple[int, Path | None, bool] | None = None
        self._lyrics_payload_key: tuple[int, Path | None] | None = None
        self._cover_track: Path | None | object = object()
        self._cover_data: str | None = None

        default_music = Path.home() / "Music"
        self._settings_error: str | None = None
        try:
            self.download_directory = load_download_directory()
        except RuntimeError as error:
            self.download_directory = default_music
            self._settings_error = str(error)
        try:
            saved_folders = load_music_folders()
        except RuntimeError as error:
            saved_folders = None
            self._settings_error = self._settings_error or str(error)
        self.music_folders = list(saved_folders or [default_music])
        if default_music not in self.music_folders:
            self.music_folders.insert(0, default_music)
        if self.download_directory not in self.music_folders:
            self.music_folders.append(self.download_directory)
        try:
            self.bitrate = load_mp3_bitrate()
        except RuntimeError as error:
            self.bitrate = 320
            self._settings_error = self._settings_error or str(error)
        try:
            self.theme = load_theme_preference()
        except RuntimeError as error:
            self.theme = "system"
            self._settings_error = self._settings_error or str(error)
        self._resolved_theme = system_theme() if self.theme == "system" else self.theme
        try:
            self.download_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._settings_error = self._settings_error or f"Could not use downloads folder: {error}"
            self.download_directory = default_music

        self.shuffle_enabled = False
        self.repeat_mode = "off"
        self.refresh_library()

    def start_services(self) -> None:
        self._command_thread = threading.Thread(
            target=self._run_command_worker,
            name="tmusic-commands",
            daemon=True,
        )
        self._command_thread.start()
        self._start_tray()
        system = platform.system()
        service_names = {
            "Linux": "MPRIS",
            "Windows": "SMTC",
            "Darwin": "NowPlaying",
        }
        name = service_names.get(system)
        if name is None:
            return
        module_name = f"platform_integration.{name}"
        self._service_thread = threading.Thread(
            target=self._run_service,
            args=(module_name,),
            name=f"tmusic-{name.casefold()}",
            daemon=True,
        )
        self._service_thread.start()

    def run_core(self) -> None:
        self._ipc_server = _CoreHTTPServer(("127.0.0.1", 0), self, self._ipc_token)
        self._ipc_thread = threading.Thread(
            target=self._ipc_server.serve_forever,
            name="tmusic-ipc",
            daemon=True,
        )
        self._ipc_thread.start()
        self.start_services()
        self.show_window()
        self._shutdown.wait()

    def ui_closed(self) -> None:
        with self._ui_lock:
            self._ui_process = None
        if self._tray_icon is None:
            self.request_close()

    def _run_command_worker(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return
            try:
                command, value = self._commands.get(timeout=1)
            except queue.Empty:
                try:
                    with self._lock:
                        if self._closed:
                            return
                        if self.player.track_finished():
                            self._advance_finished_track()
                except (OSError, RuntimeError, ValueError, IndexError) as error:
                    self._last_error = str(error)
                continue
            try:
                self._dispatch(command, value)
            except (OSError, RuntimeError, ValueError, IndexError) as error:
                self._last_error = str(error)

    def _run_service(self, module_name: str) -> None:
        try:
            service_module = importlib.import_module(module_name)
            service = service_module.create_service(self.player, self._queue_command)
            with self._lock:
                if self._closed:
                    service.stop()
                    return
                self._service = service
            service.start()
        except (ImportError, OSError, RuntimeError) as error:
            self._last_error = f"Media controls unavailable: {error}"

    def _start_tray(self) -> None:
        try:
            from utils.system_tray import create_system_tray

            self._tray_icon = create_system_tray(
                self.show_window,
                self.close,
                self.toggle_play,
                self.previous_track,
                self.next_track,
            )

            def show_tray(icon: Any) -> None:
                with self._lock:
                    if not self._closed:
                        icon.visible = True

            self._tray_icon.run_detached(setup=show_tray)
        except (ImportError, OSError, RuntimeError, AttributeError) as error:
            self._last_error = f"System tray unavailable: {error}"
            self._tray_icon = None

    def _queue_command(self, command: str, value: object | None = None) -> None:
        self._commands.put((command, value))

    def _process_commands(self) -> None:
        while True:
            try:
                command, value = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                self._dispatch(command, value)
            except (OSError, RuntimeError, ValueError, IndexError) as error:
                self._last_error = str(error)

    def _dispatch(self, command: str, value: object | None = None) -> None:
        with self._lock:
            if command in {"toggle", "play_pause"}:
                self.player.toggle_play_pause()
            elif command == "play":
                self.player.play()
            elif command == "pause":
                self.player.pause()
            elif command == "stop":
                self.player.stop()
            elif command == "next":
                self.player.next_track()
            elif command == "previous":
                self.player.previous_track()
            elif command == "seek":
                self.player.seek(float(value or 0))
            elif command == "seek_by":
                self.player.seek(self.player.position + float(value or 0))
            elif command == "shuffle":
                self.shuffle_enabled = bool(value)
                self.player.shuffle = self.shuffle_enabled
            elif command == "repeat":
                self.set_repeat(str(value))
            elif command == "volume":
                self.player.set_volume(float(value or 0))
            elif command == "raise":
                self.show_window()
            elif command == "quit":
                self.close()

    def get_state(self, full: bool = False) -> dict[str, object]:
        self._process_commands()
        with self._lock:
            track = self.player.current_track
            cover_changed = full or track != self._cover_track
            if cover_changed:
                self._cover_track = track
                cover = read_cover_art(track) if track is not None else None
                self._cover_data = self._cover_preview(cover) if cover else None

            duration = self.player.duration
            position = self.player.position
            lyrics = self.player.lyrics
            active_lyric = self.player.active_lyric_index()
            metadata = self.player.track_metadata
            track_payload_key = (self._library_revision, track, self.player.is_playing)
            tracks_changed = full or track_payload_key != self._track_payload_key
            rows: list[dict[str, object]] | None = None
            if tracks_changed:
                self._track_payload_key = track_payload_key
                rows = [
                    {
                        "path": str(path),
                        "title": self._track_title(path),
                        "artist": self._track_artist(path),
                        "active": path == track,
                    }
                    for path in self.player.tracks
                ]
            lyrics_payload_key = (self._library_revision, track)
            lyrics_changed = full or lyrics_payload_key != self._lyrics_payload_key
            if lyrics_changed:
                self._lyrics_payload_key = lyrics_payload_key
            state = {
                "libraryRevision": self._library_revision,
                "currentPath": str(track) if track else None,
                "title": self._track_title(track) if track else "Choose a track",
                "artist": self._track_artist(track) if track else "Your library is ready",
                "album": metadata.get("album", ""),
                "playing": self.player.is_playing,
                "paused": self.player.is_paused,
                "position": position,
                "duration": duration,
                "volume": self.player.volume,
                "shuffle": self.shuffle_enabled,
                "repeat": self.repeat_mode,
                "activeLyric": active_lyric,
                "lyricsSynced": self.player.lyrics_synced,
                "folders": [str(folder) for folder in self.music_folders],
                "downloadDirectory": str(self.download_directory),
                "bitrate": self.bitrate,
                "theme": self.theme,
                "resolvedTheme": self._resolved_theme,
                "download": {
                    "active": self._download_active,
                    "progress": dict(self._download_progress),
                    "error": self._download_error,
                    "finished": self._download_finished,
                },
                "update": {
                    "checking": self._update_checking,
                    "result": self._update_result,
                },
                "status": self._last_error or self._last_status,
                "error": self._last_error,
                "settingsError": self._settings_error,
            }
            if rows is not None:
                state["tracks"] = rows
            if lyrics_changed:
                state["lyrics"] = [
                    {"timestamp": line.timestamp, "text": line.text}
                    for line in lyrics
                ]
            if cover_changed:
                state["cover"] = self._cover_data
            return state

    def _track_title(self, track: Path | None) -> str:
        if track is None:
            return ""
        return self.player.track_metadata.get("title", track.stem) if track == self.player.current_track else track.stem

    def _track_artist(self, track: Path | None) -> str:
        if track is None:
            return ""
        if track == self.player.current_track:
            return self.player.track_metadata.get("artist", "Unknown artist")
        return "Unknown artist"

    def _advance_finished_track(self) -> None:
        if self.repeat_mode == "one" and self.player.current_index is not None:
            self.player.play_index(self.player.current_index)
        elif self.repeat_mode == "all" or self.shuffle_enabled:
            self.player.next_track()
        else:
            self.player.stop()

    def refresh_library(self) -> None:
        with self._lock:
            tracks = discover_tracks(self.music_folders)
            self.player.set_library(tracks)
            self._library_revision += 1
            self._last_status = f"{len(tracks)} tracks in your library"
            self._last_error = None

    def play_track(self, path: str) -> bool:
        try:
            with self._lock:
                target = Path(path)
                index = self.player.tracks.index(target)
                self.player.play_index(index)
        except (ValueError, OSError, RuntimeError, IndexError) as error:
            self._last_error = f"Could not play track: {error}"
            return False
        self._last_error = None
        self._last_status = f"Playing {target.name}"
        self._cover_track = None
        return True

    def toggle_play(self) -> None:
        self._run_player_action(self.player.toggle_play_pause)

    def play(self) -> None:
        self._run_player_action(self.player.play)

    def pause(self) -> None:
        self._run_player_action(self.player.pause)

    def stop(self) -> None:
        self._run_player_action(self.player.stop)

    def next_track(self) -> None:
        self._run_player_action(self.player.next_track)

    def previous_track(self) -> None:
        self._run_player_action(self.player.previous_track)

    def _run_player_action(self, action: Any) -> None:
        try:
            with self._lock:
                action()
            self._last_error = None
        except (OSError, RuntimeError, ValueError, IndexError) as error:
            self._last_error = str(error)

    def seek(self, seconds: object) -> None:
        try:
            with self._lock:
                self.player.seek(float(seconds))
        except (TypeError, ValueError) as error:
            self._last_error = f"Invalid seek position: {error}"

    def set_volume(self, value: object) -> None:
        try:
            with self._lock:
                self.player.set_volume(float(value))
        except (TypeError, ValueError) as error:
            self._last_error = f"Invalid volume: {error}"

    def set_shuffle(self, enabled: object) -> None:
        with self._lock:
            self.shuffle_enabled = bool(enabled)
            self.player.shuffle = self.shuffle_enabled

    def set_repeat(self, mode: str) -> None:
        if mode not in {"off", "all", "one"}:
            raise ValueError("Repeat mode must be off, all, or one.")
        with self._lock:
            self.repeat_mode = mode
            self.player.repeat_mode = mode

    def add_music_folder(self, value: str) -> str | None:
        folder = Path(value).expanduser().resolve()
        if folder in self.music_folders:
            return None
        self.music_folders.append(folder)
        try:
            save_music_folders(self.music_folders)
        except RuntimeError:
            self.music_folders.remove(folder)
            raise
        self.refresh_library()
        return str(folder)

    def remove_music_folder(self, value: str) -> None:
        folder = Path(value)
        if folder not in self.music_folders:
            return
        self.music_folders.remove(folder)
        try:
            save_music_folders(self.music_folders)
        except RuntimeError:
            self.music_folders.append(folder)
            raise
        self.refresh_library()

    def set_download_folder(self, value: str) -> str:
        directory = Path(value).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        save_download_directory(directory)
        with self._lock:
            self.download_directory = directory
        return str(directory)

    def set_bitrate(self, value: object) -> None:
        try:
            bitrate = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Choose 192, 256, or 320 kbps.") from error
        if bitrate not in BITRATES:
            raise ValueError("Choose 192, 256, or 320 kbps.")
        save_mp3_bitrate(bitrate)
        with self._lock:
            self.bitrate = bitrate

    def set_theme(self, theme: str) -> None:
        save_theme_preference(theme)
        self.theme = theme
        self._resolved_theme = system_theme() if theme == "system" else theme

    def get_editor_data(self, path_value: str) -> dict[str, object]:
        path = Path(path_value)
        if path.suffix.casefold() != ".mp3":
            raise ValueError("Metadata editing is available for MP3 files only.")
        metadata = self._read_easy_tags(path)
        lyrics, _synced = read_track_lyrics(path)
        lyrics_text = "\n".join(
            f"[{int(line.timestamp) // 60:02}:{line.timestamp % 60:05.2f}]{line.text}"
            for line in lyrics
        )
        cover = read_cover_art(path)
        cover_data = self._cover_preview(cover) if cover else None
        return {
            "path": str(path),
            "title": metadata.get("title", path.stem),
            "artist": metadata.get("artist", ""),
            "lyrics": lyrics_text,
            "cover": cover_data,
        }

    def _read_easy_tags(self, path: Path) -> dict[str, str]:
        from mutagen import File as MutagenFile
        from mutagen import MutagenError

        try:
            audio = MutagenFile(path, easy=True)
        except (OSError, MutagenError) as error:
            raise RuntimeError(f"Could not read MP3 metadata: {error}") from error
        tags = audio.tags if audio is not None else None
        result: dict[str, str] = {}
        for key in ("title", "artist"):
            values = tags.get(key) if tags is not None else None
            if values:
                result[key] = str(values[0] if isinstance(values, list) else values)
        return result

    def get_cover_preview(self, value: str) -> dict[str, str]:
        path = Path(value)
        if path.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            raise ValueError("Choose a JPEG, PNG, GIF, or WebP cover image.")
        data = path.read_bytes()
        if len(data) > 12 * 1024 * 1024:
            raise ValueError("Cover images must be 12 MiB or smaller.")
        try:
            from PIL import Image
            with Image.open(BytesIO(data)) as image:
                image.verify()
        except (OSError, ValueError) as error:
            raise ValueError(f"Could not read the selected cover image: {error}") from error
        return {
            "path": str(path),
            "preview": self._cover_preview(data),
        }

    def save_editor(
        self,
        path_value: str,
        title: str,
        artist: str,
        lyrics: str,
        cover_path: str | None,
    ) -> str:
        path = Path(path_value)
        current = self.player.current_track == path
        was_playing = self.player.is_playing
        if current:
            self.player.stop()
            self.player.unload()
        try:
            destination = save_mp3_metadata(
                path,
                title=title,
                artist=artist,
                lrc_text=lyrics,
                cover_path=Path(cover_path) if cover_path else None,
            )
        except (OSError, RuntimeError, ValueError):
            if current:
                self._resume_after_edit(path, was_playing)
            raise
        self.refresh_library()
        if current:
            self._resume_after_edit(destination, was_playing)
        self._cover_track = None
        self._last_status = f"Updated {destination.name}"
        return str(destination)

    def _resume_after_edit(self, track: Path, was_playing: bool) -> None:
        try:
            index = self.player.tracks.index(track)
            self.player.play_index(index)
            if not was_playing:
                self.player.pause()
        except (ValueError, OSError, RuntimeError) as error:
            self._last_error = f"Track metadata saved, but playback could not resume: {error}"

    def start_download(self, url: str) -> bool:
        if not url.strip():
            raise ValueError("Enter a video or playlist URL.")
        with self._lock:
            if self._download_active:
                return False
            self._download_cancel.clear()
            self._download_error = None
            self._download_finished = None
            self._download_progress = {"status": "Starting download"}
            self._download_active = True
            self._download_thread = threading.Thread(
                target=self._download_worker,
                args=(url.strip(),),
                name="tmusic-downloader",
                daemon=True,
            )
            self._download_thread.start()
        return True

    def _download_worker(self, url: str) -> None:
        try:
            from core.downloader import Downloader

            with self._lock:
                download_directory = self.download_directory
                bitrate = self.bitrate
            downloader = Downloader(download_directory, bitrate)

            def progress(data: dict[str, object]) -> None:
                with self._lock:
                    self._download_progress = {
                        key: data[key]
                        for key in (
                            "status",
                            "downloaded_bytes",
                            "total_bytes",
                            "_percent_str",
                            "speed",
                            "eta",
                        )
                        if key in data
                    }

            path = downloader.download_audio(
                url,
                progress_callback=progress,
                cancellation_event=self._download_cancel,
            )
        except (OSError, RuntimeError, ValueError) as error:
            with self._lock:
                self._download_error = str(error)
        else:
            with self._lock:
                self._download_finished = str(path)
            self.refresh_library()
        finally:
            with self._lock:
                self._download_active = False

    def cancel_download(self) -> None:
        self._download_cancel.set()

    def check_for_updates(self) -> None:
        with self._lock:
            if self._update_checking:
                return
            self._update_checking = True
            self._update_result = None
            threading.Thread(
                target=self._check_update_worker,
                name="tmusic-update-check",
                daemon=True,
            ).start()

    def _check_update_worker(self) -> None:
        request = urllib.request.Request(
            "https://api.github.com/repos/InvaerLabs/Tmusic/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Tmusic"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                release = json.loads(response.read().decode("utf-8"))
            tag = release.get("tag_name")
            url = release.get("html_url")
            if not isinstance(tag, str) or not isinstance(url, str):
                raise ValueError("GitHub returned an incomplete release response.")
            version = tuple(int(part) for part in re.findall(r"\d+", tag))
            if not version:
                raise ValueError("GitHub returned an invalid release version.")
            while version and version[-1] == 0:
                version = version[:-1]
            current_version = tuple(int(part) for part in APP_VERSION.split("."))
            while current_version and current_version[-1] == 0:
                current_version = current_version[:-1]
            with self._lock:
                self._update_result = {
                    "kind": "available" if version > current_version else "current",
                    "tag": tag,
                    "url": url,
                }
        except (OSError, ValueError, json.JSONDecodeError) as error:
            with self._lock:
                self._update_result = {"kind": "error", "message": str(error)}
        finally:
            with self._lock:
                self._update_checking = False

    def open_release(self, url: str) -> bool:
        expected_prefix = "https://github.com/InvaerLabs/Tmusic/releases/"
        if not url.startswith(expected_prefix):
            raise ValueError("Only official Tmusic release links can be opened.")
        if not webbrowser.open(url):
            self._last_error = "No browser accepted the release link."
            return False
        return True

    def show_window(self) -> None:
        if self._ipc_server is None:
            return
        with self._ui_lock:
            if self._closed:
                return
            if self._ui_process is not None:
                exit_code = self._ui_process.poll()
                if exit_code is None:
                    return
                self._ui_process = None
                if exit_code != 0:
                    self._last_error = (
                        f"The previous Tmusic window exited with code {exit_code}."
                    )
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve().parents[1] / "main.pyw"))
            command.extend(
                [
                    "--tmusic-ui",
                    "127.0.0.1",
                    str(self._ipc_server.server_address[1]),
                    self._ipc_token,
                ]
            )
            options: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                options["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            else:
                options["start_new_session"] = True
            try:
                self._ui_process = subprocess.Popen(command, **options)
            except OSError as error:
                self._last_error = f"Could not open the Tmusic window: {error}"

    def _stop_ui_process(self) -> None:
        with self._ui_lock:
            process = self._ui_process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._download_cancel.set()
            service = self._service
        self._shutdown.set()
        self._stop_ui_process()
        cleanup_errors: list[str] = []
        if service is not None:
            try:
                service.stop()
            except (OSError, RuntimeError) as error:
                cleanup_errors.append(f"Could not stop media controls: {error}")
        if (
            self._command_thread is not None
            and self._command_thread is not threading.current_thread()
        ):
            self._command_thread.join(timeout=1)
        if self._service_thread is not None and self._service_thread is not threading.current_thread():
            self._service_thread.join(timeout=1)
        if self._tray_icon is not None:
            try:
                from utils.system_tray import stop_system_tray

                stop_system_tray(self._tray_icon)
            except (ImportError, OSError, RuntimeError) as error:
                cleanup_errors.append(f"Could not remove the system tray icon: {error}")
        if self._ipc_server is not None:
            self._ipc_server.shutdown()
            self._ipc_server.server_close()
        if self._ipc_thread is not None and self._ipc_thread is not threading.current_thread():
            self._ipc_thread.join(timeout=1)
        if self._download_thread is not None and self._download_thread is not threading.current_thread():
            self._download_thread.join(timeout=3)
        try:
            self.player.shutdown()
        except (OSError, RuntimeError) as error:
            cleanup_errors.append(f"Could not stop audio playback: {error}")
        if cleanup_errors:
            self._last_error = "; ".join(cleanup_errors)

    def request_close(self) -> None:
        threading.Thread(
            target=self.close,
            name="tmusic-close",
            daemon=True,
        ).start()

    @staticmethod
    def _cover_mime(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        return "image/jpeg"

    @classmethod
    def _cover_preview(cls, data: bytes) -> str:
        try:
            from PIL import Image

            with Image.open(BytesIO(data)) as image:
                image.thumbnail((512, 512))
                preview = BytesIO()
                image.convert("RGB").save(
                    preview,
                    format="JPEG",
                    quality=82,
                    optimize=True,
                )
            data = preview.getvalue()
            mime = "image/jpeg"
        except (OSError, ValueError):
            mime = cls._cover_mime(data)
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def create_webview(host: str, port: int, token: str) -> None:
    import webview

    bridge = _WebViewAPI(_CoreClient(host, port, token))
    screens = webview.screens
    screen_width = screens[0].width if screens else 1280
    screen_height = screens[0].height if screens else 800
    width = max(320, min(max(860, int(screen_width * 0.84)), 1280, screen_width - 32))
    height = max(320, min(max(620, int(screen_height * 0.86)), 900, screen_height - 48))
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    assets = _asset_directory()
    if not (assets / "index.html").is_file():
        raise RuntimeError(
            "The local web interface has not been built. Run `npm ci && npm run build` in src/webui."
        )
    window = webview.create_window(
        "Tmusic",
        (assets / "index.html").as_uri(),
        js_api=bridge,
        width=width,
        height=height,
        min_size=(min(640, width), min(480, height)),
        x=x,
        y=y,
        frameless=True,
        easy_drag=False,
    )
    bridge.attach_window(window, x, y)
    window.events.closing += bridge.on_window_closing
    window.events.closed += bridge.on_window_closed
    webview.start(debug=False)


def _asset_directory() -> Path:
    if "__compiled__" in globals() or getattr(sys, "_MEIPASS", None):
        return resource_path("webui", "dist")
    return Path(__file__).resolve().parents[1] / "webui" / "dist"


def main() -> None:
    if len(sys.argv) == 5 and sys.argv[1] == "--tmusic-ui":
        create_webview(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        return
    bridge = TmusicBridge()
    try:
        bridge.run_core()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
