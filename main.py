from __future__ import annotations

import threading
import queue
import platform
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pygame

from downloader import Downloader
from preferences import (
    load_download_directory,
    load_theme_preference,
    save_download_directory,
    save_theme_preference,
    system_theme,
)
from player import (
    LyricLine,
    MusicPlayer,
    discover_tracks,
    format_lrc,
    format_time,
    read_track_lyrics,
    save_mp3_metadata,
)


BG = "#0d1010"
PANEL = "#151a19"
PANEL_LIGHT = "#1d2421"
ACCENT = "#c3f27a"
TEXT = "#f1f3ed"
MUTED = "#89918a"
LINE = "#29312d"


class TmusicApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Tmusic — Local Player")
        self.root.geometry("1120x760")
        self.root.minsize(860, 620)
        self.root.configure(bg=BG)

        self.player = MusicPlayer()
        default_music = Path.home() / "Music"
        try:
            self.download_directory = load_download_directory()
        except RuntimeError as error:
            self.download_directory = default_music
            self._settings_error = str(error)
        else:
            self._settings_error = None
        self.music_folders = list(dict.fromkeys((default_music, self.download_directory)))
        try:
            self.downloader = Downloader(self.download_directory)
        except OSError as error:
            self.download_directory = default_music
            self.music_folders = [default_music]
            self.downloader = Downloader(default_music)
            self._settings_error = f"Could not use download folder: {error}"
        legacy_downloads = Path(__file__).resolve().parent / "downloads"
        if legacy_downloads.is_dir() and legacy_downloads not in self.music_folders:
            self.music_folders.append(legacy_downloads)

        self.shuffle_enabled = False
        self.repeat_mode = "off"
        self._seeking = False
        self._last_lyric_index: int | None = None
        self._lyrics: list[LyricLine] = []
        self._closing = False
        self._background_messages: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._download_messages: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self._mpris_commands: queue.SimpleQueue[tuple[str, object | None]] = queue.SimpleQueue()
        self._tray_icon = None
        self._tray_error: str | None = None
        self._download_active = False
        self._displayed_track: Path | None = None
        self.lyrics_panel: tk.Frame | None = None
        self.lyrics_view: tk.Text | None = None
        self._lyrics_visible = False
        try:
            self.theme_preference = load_theme_preference()
        except RuntimeError as error:
            self.theme_preference = "system"
            self._settings_error = self._settings_error or str(error)
        self.theme_name = (
            system_theme() if self.theme_preference == "system" else self.theme_preference
        )
        self.theme_colors = self._theme_palette(self.theme_name)

        self._build_ui()
        self._apply_theme()
        self.refresh_library()
        self._bind_shortcuts()
        if platform.system() == "Linux":
            self._start_system_tray()
            self._start_mpris()
            self.root.bind_all("<Mod4-q>", self._hide_window)
            self.root.bind_all("<Mod4-Q>", self._hide_window)
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.root.title("Tmusic 2.0 — Local Player")
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        header = tk.Frame(self.root, bg=BG, height=70)
        header.grid(row=0, column=0, sticky="ew", padx=30)
        header.grid_columnconfigure(1, weight=1)
        tk.Label(
            header, text="T / MUSIC", bg=BG, fg=ACCENT,
            font=("TkDefaultFont", 17, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=20)
        tk.Label(
            header, text="A QUIET PLACE FOR YOUR MUSIC", bg=BG, fg=MUTED,
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=30)
        self.header_status = tk.Label(
            header, text="LOCAL PLAYER  •  READY", bg=BG, fg=MUTED,
            font=("TkDefaultFont", 9, "bold"),
        )
        self.header_status.grid(row=0, column=2, sticky="e")
        self.theme_button = self._button(
            header, self._theme_button_label(), self.toggle_theme, subtle=True
        )
        self.theme_button.grid(row=0, column=3, sticky="e", padx=(14, 0))

        body = tk.Frame(self.root, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 18))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=290, weight=0)
        body.grid_columnconfigure(1, weight=1)

        self._build_library(body)
        self._build_now_playing(body)
        self._build_transport()

    def _build_library(self, parent: tk.Frame) -> None:
        sidebar = tk.Frame(parent, bg=PANEL, padx=18, pady=18)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        tabs = tk.Frame(sidebar, bg=PANEL)
        tabs.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        tabs.grid_columnconfigure(0, weight=1)
        tabs.grid_columnconfigure(1, weight=1)
        self.library_tab_button = self._button(
            tabs, "LIBRARY", lambda: self._show_sidebar_page("library"), subtle=True
        )
        self.library_tab_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.download_tab_button = self._button(
            tabs, "DOWNLOAD", lambda: self._show_sidebar_page("download"), subtle=True
        )
        self.download_tab_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.sidebar_pages = tk.Frame(sidebar, bg=PANEL)
        self.sidebar_pages.grid(row=1, column=0, rowspan=2, sticky="nsew")
        self.sidebar_pages.grid_rowconfigure(0, weight=1)
        self.sidebar_pages.grid_columnconfigure(0, weight=1)

        self.library_page = tk.Frame(self.sidebar_pages, bg=PANEL)
        self.library_page.grid(row=0, column=0, sticky="nsew")
        self.library_page.grid_rowconfigure(2, weight=1)
        self.library_page.grid_columnconfigure(0, weight=1)
        title_row = tk.Frame(self.library_page, bg=PANEL)
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)
        tk.Label(title_row, text="YOUR LIBRARY", bg=PANEL, fg=TEXT,
                 font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.track_count = tk.Label(title_row, text="0 TRACKS", bg=PANEL, fg=MUTED,
                                    font=("TkDefaultFont", 8, "bold"))
        self.track_count.grid(row=0, column=1, sticky="e")

        actions = tk.Frame(self.library_page, bg=PANEL)
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 12))
        self._button(actions, "＋  Add folder", self.add_folder, subtle=True).pack(
            side="left", fill="x", expand=True
        )
        self._button(actions, "↻", self.refresh_library, subtle=True, width=3).pack(
            side="left", padx=(8, 0)
        )
        list_frame = tk.Frame(self.library_page, bg=PANEL)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        self.track_list = tk.Listbox(
            list_frame,
            bg=PANEL,
            fg=TEXT,
            selectbackground="#33402c",
            selectforeground=ACCENT,
            activestyle="none",
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            font=("TkDefaultFont", 10),
            selectmode=tk.SINGLE,
            exportselection=False,
        )
        self.track_list.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(
            list_frame, orient="vertical", command=self.track_list.yview,
            bg=PANEL_LIGHT, troughcolor=PANEL, relief="flat", borderwidth=0,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.track_list.configure(yscrollcommand=scrollbar.set)
        self.track_list.bind("<Double-Button-1>", self._play_selection)
        self.track_list.bind("<Return>", self._play_selection)
        self.track_list.bind("<Button-3>", self._show_track_menu)
        if platform.system() == "Darwin":
            self.track_list.bind("<Control-Button-1>", self._show_track_menu)

        self.library_hint = tk.Label(
            self.library_page,
            text="Choose a folder to add your music.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            justify="left",
            font=("TkDefaultFont", 9),
        )
        self.library_hint.grid(row=3, column=0, sticky="ew", pady=(12, 0))

        self.download_page = tk.Frame(self.sidebar_pages, bg=PANEL)
        self.download_page.grid(row=0, column=0, sticky="nsew")
        self.download_page.grid_columnconfigure(0, weight=1)
        tk.Label(
            self.download_page, text="DOWNLOAD MUSIC", bg=PANEL, fg=TEXT,
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            self.download_page,
            text="Copy a video link, then use one click to download its audio.",
            bg=PANEL, fg=MUTED, justify="left", wraplength=245,
            font=("TkDefaultFont", 9),
        ).grid(row=1, column=0, sticky="w", pady=(10, 18))
        self.download_button = self._button(
            self.download_page, "↓  Paste link & download",
            self.start_download, primary=True,
        )
        self.download_button.grid(row=2, column=0, sticky="ew")
        self.download_progress = ttk.Progressbar(
            self.download_page, mode="determinate", maximum=100, style="TProgressbar"
        )
        self.download_progress.grid(row=3, column=0, sticky="ew", pady=(18, 8))
        self.download_status = tk.Label(
            self.download_page, text="MP3 • 192 kbps", bg=PANEL, fg=MUTED,
            anchor="w", justify="left", wraplength=245,
            font=("TkDefaultFont", 9),
        )
        self.download_status.grid(row=6, column=0, sticky="ew")
        tk.Label(
            self.download_page, text="SAVE TO", bg=PANEL, fg=TEXT,
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=4, column=0, sticky="w", pady=(24, 6))
        destination_row = tk.Frame(self.download_page, bg=PANEL)
        destination_row.grid(row=5, column=0, sticky="ew")
        destination_row.grid_columnconfigure(0, weight=1)
        self.download_directory_label = tk.Label(
            destination_row,
            text=str(self.download_directory),
            bg=PANEL_LIGHT,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=175,
            font=("TkDefaultFont", 8),
            padx=8,
            pady=8,
        )
        self.download_directory_label.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.choose_download_directory_button = self._button(
            destination_row, "Choose", self.choose_download_directory, subtle=True
        )
        self.choose_download_directory_button.grid(row=0, column=1, sticky="e")
        if self._settings_error:
            self.download_status.configure(text=self._settings_error, fg="#ff8b82")
        self._show_sidebar_page("library")

    def _show_sidebar_page(self, page: str) -> None:
        if page == "download":
            self.download_page.tkraise()
            self.download_tab_button.configure(fg=ACCENT, bg="#29351f")
            self.library_tab_button.configure(fg=TEXT, bg=PANEL_LIGHT)
        else:
            self.library_page.tkraise()
            self.library_tab_button.configure(fg=ACCENT, bg="#29351f")
            self.download_tab_button.configure(fg=TEXT, bg=PANEL_LIGHT)

    def start_download(self) -> None:
        try:
            url = self.root.clipboard_get().strip()
        except tk.TclError:
            self.download_status.configure(
                text="Clipboard is empty or does not contain text.",
                fg="#ff8b82",
            )
            return
        if not url:
            self.download_status.configure(
                text="Copy a video link to the clipboard first.",
                fg="#ff8b82",
            )
            return
        if self._download_active:
            return

        self._download_active = True
        self.download_button.configure(state="disabled", text="Downloading…")
        self.download_progress.configure(value=0, mode="indeterminate")
        self.download_progress.start(12)
        self.download_status.configure(text="Connecting to source…", fg=MUTED)
        threading.Thread(
            target=self._download_worker,
            args=(url,),
            name="tmusic-downloader",
            daemon=True,
        ).start()

    def choose_download_directory(self) -> None:
        if self._download_active:
            self.download_status.configure(
                text="Wait for the current download to finish before changing folders.",
                fg="#ff8b82",
            )
            return

        selected = filedialog.askdirectory(
            title="Choose download folder",
            initialdir=self.download_directory,
            mustexist=False,
        )
        if not selected:
            return
        directory = Path(selected).expanduser().resolve()
        try:
            downloader = Downloader(directory)
            save_download_directory(directory)
        except (OSError, RuntimeError) as error:
            self.download_status.configure(text=str(error), fg="#ff8b82")
            self._set_status(f"Could not change download folder: {error}", error=True)
            return

        self.downloader = downloader
        self.download_directory = directory
        if directory not in self.music_folders:
            self.music_folders.append(directory)
        self.download_directory_label.configure(text=str(directory))
        self.download_status.configure(text="Download folder updated.", fg=ACCENT)
        self.refresh_library()

    def _download_worker(self, url: str) -> None:
        try:
            path = self.downloader.download_audio(
                url,
                progress_callback=lambda progress: self._download_messages.put(
                    ("progress", progress)
                ),
            )
        except (OSError, RuntimeError, ValueError) as error:
            self._download_messages.put(("error", str(error)))
        else:
            self._download_messages.put(("complete", path))

    def _build_now_playing(self, parent: tk.Frame) -> None:
        content = tk.Frame(parent, bg=BG)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(3, weight=1)
        content.grid_columnconfigure(0, weight=1)

        eyebrow = tk.Label(
            content, text="NOW PLAYING", bg=BG, fg=ACCENT,
            font=("TkDefaultFont", 9, "bold"),
        )
        eyebrow.grid(row=0, column=0, sticky="w", pady=(8, 5))
        self.track_title = tk.Label(
            content, text="Pick something to play", bg=BG, fg=TEXT,
            font=("TkDefaultFont", 20, "bold"), anchor="w",
        )
        self.track_title.grid(row=1, column=0, sticky="ew")
        self.track_subtitle = tk.Label(
            content, text="Your local library, ready when you are.", bg=BG,
            fg=MUTED, font=("TkDefaultFont", 10), anchor="w",
        )
        self.track_subtitle.grid(row=2, column=0, sticky="ew", pady=(5, 12))

        artwork_and_lyrics = tk.Frame(content, bg=BG)
        artwork_and_lyrics.grid(row=3, column=0, sticky="nsew")
        artwork_and_lyrics.grid_rowconfigure(2, weight=1)
        artwork_and_lyrics.grid_columnconfigure(0, weight=1)

        self.cover = tk.Canvas(
            artwork_and_lyrics, height=210, bg=BG,
            highlightthickness=0, borderwidth=0,
        )
        self.cover.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.cover.bind("<Configure>", self._draw_record)

        self.current_lyric = tk.Label(
            artwork_and_lyrics,
            text="Select a track to view lyrics",
            bg=BG, fg=MUTED, anchor="w", font=("TkDefaultFont", 10, "italic"),
        )
        self.current_lyric.grid(row=1, column=0, sticky="ew", pady=(10, 8))

        self.lyrics_panel = tk.Frame(artwork_and_lyrics, bg=PANEL, padx=14, pady=12)
        self.lyrics_panel.grid(row=2, column=0, sticky="nsew")
        self.lyrics_panel.grid_columnconfigure(0, weight=1)
        self.lyrics_panel.grid_rowconfigure(1, weight=1)
        self.lyrics_title = tk.Label(
            self.lyrics_panel, text="LYRICS", bg=PANEL, fg=ACCENT,
            anchor="w", font=("TkDefaultFont", 9, "bold"),
        )
        self.lyrics_title.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        lyrics_frame = tk.Frame(self.lyrics_panel, bg=PANEL)
        lyrics_frame.grid(row=1, column=0, sticky="nsew")
        lyrics_frame.grid_columnconfigure(0, weight=1)
        lyrics_frame.grid_rowconfigure(0, weight=1)
        self.lyrics_view = tk.Text(
            lyrics_frame, height=6, bg=PANEL, fg=MUTED, insertbackground=ACCENT,
            selectbackground="#33402c", wrap="word", borderwidth=0,
            highlightthickness=0, font=("TkDefaultFont", 12),
            spacing1=5, spacing3=5, padx=8, pady=8, state="disabled",
        )
        self.lyrics_view.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(
            lyrics_frame, orient="vertical", command=self.lyrics_view.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.lyrics_view.configure(yscrollcommand=scrollbar.set)
        self.lyrics_view.tag_configure(
            "active", foreground=ACCENT, font=("TkDefaultFont", 12, "bold")
        )
        self.lyrics_view.tag_configure("line", foreground=MUTED)
        self.lyrics_view.bind("<Button-1>", self._seek_to_lyric)
        self.lyrics_action = self._button(
            self.lyrics_panel, "＋  Add or edit lyrics",
            self._edit_current_lyrics, subtle=True,
        )
        self.lyrics_action.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.lyrics_panel.grid_remove()

    def _build_transport(self) -> None:
        transport = tk.Frame(self.root, bg=PANEL, padx=28, pady=15)
        transport.grid(row=2, column=0, sticky="ew")
        transport.grid_columnconfigure(1, weight=1)

        left = tk.Frame(transport, bg=PANEL)
        left.grid(row=0, column=0, sticky="w")
        self.lyric_button = self._button(
            left, "Lyric", self.toggle_lyrics_panel, subtle=True
        )
        self.lyric_button.pack(side="left")

        center = tk.Frame(transport, bg=PANEL)
        center.grid(row=0, column=1, sticky="ew", padx=34)
        center.grid_columnconfigure(1, weight=1)
        controls = tk.Frame(center, bg=PANEL)
        controls.grid(row=0, column=0, columnspan=3, pady=(0, 8))
        self.shuffle_button = self._button(
            controls, "⤨", self.toggle_shuffle, subtle=True, width=3
        )
        self.shuffle_button.pack(side="left", padx=(0, 13))
        self._button(controls, "|◀", self.previous_track, subtle=True, width=4).pack(
            side="left", padx=4
        )
        self.play_button = self._button(
            controls, "▶", self.toggle_play, primary=True, width=5
        )
        self.play_button.pack(side="left", padx=8)
        self._button(controls, "▶|", self.next_track, subtle=True, width=4).pack(
            side="left", padx=4
        )
        self.repeat_button = self._button(
            controls, "↻", self.toggle_repeat, subtle=True, width=3
        )
        self.repeat_button.pack(side="left", padx=(13, 0))

        self.elapsed_label = tk.Label(
            center, text="00:00", bg=PANEL, fg=MUTED,
            font=("TkDefaultFont", 8),
        )
        self.elapsed_label.grid(row=1, column=0, sticky="e", padx=(0, 10))
        self.seek_scale = tk.Scale(
            center, from_=0, to=1, orient="horizontal", showvalue=0,
            resolution=0.1, sliderlength=13, width=4, bd=0,
            bg=PANEL, fg=MUTED, troughcolor=LINE, activebackground=ACCENT,
            highlightthickness=0, command=self._seek_changed,
        )
        self.seek_scale.grid(row=1, column=1, sticky="ew")
        self.seek_scale.bind("<ButtonPress-1>", self._begin_seek)
        self.seek_scale.bind("<ButtonRelease-1>", self._finish_seek)
        self.duration_label = tk.Label(
            center, text="--:--", bg=PANEL, fg=MUTED,
            font=("TkDefaultFont", 8),
        )
        self.duration_label.grid(row=1, column=2, sticky="w", padx=(10, 0))

        volume = tk.Frame(transport, bg=PANEL)
        volume.grid(row=0, column=2, sticky="e")
        tk.Label(volume, text="VOL", bg=PANEL, fg=MUTED, font=("TkDefaultFont", 8, "bold")).pack(
            side="left", padx=(0, 6)
        )
        self.volume_scale = tk.Scale(
            volume, from_=0, to=100, orient="horizontal", showvalue=0,
            resolution=1, sliderlength=12, width=4, length=96, bd=0,
            bg=PANEL, fg=MUTED, troughcolor=LINE, activebackground=ACCENT,
            highlightthickness=0, command=self._volume_changed,
        )
        self.volume_scale.set(self.player.volume * 100)
        self.volume_scale.pack(side="left")

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        primary: bool = False,
        subtle: bool = False,
        width: int | None = None,
    ) -> tk.Button:
        background = ACCENT if primary else (PANEL_LIGHT if subtle else PANEL)
        foreground = "#10140d" if primary else (TEXT if subtle else MUTED)
        options = {
            "text": text,
            "command": command,
            "bg": background,
            "fg": foreground,
            "activebackground": "#d4ff91" if primary else "#28312c",
            "activeforeground": "#10140d" if primary else ACCENT,
            "disabledforeground": MUTED,
            "relief": "flat",
            "borderwidth": 0,
            "cursor": "hand2",
            "font": ("TkDefaultFont", 9, "bold"),
            "padx": 12,
            "pady": 8,
        }
        if width is not None:
            options["width"] = width
        return tk.Button(parent, **options)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<space>", self._space_shortcut)
        self.root.bind("<Control-Right>", self._next_shortcut)
        self.root.bind("<Control-Left>", self._previous_shortcut)

    def _space_shortcut(self, _event: tk.Event) -> str:
        self.toggle_play()
        return "break"

    def _next_shortcut(self, _event: tk.Event) -> str:
        self.next_track()
        return "break"

    def _previous_shortcut(self, _event: tk.Event) -> str:
        self.previous_track()
        return "break"

    def refresh_library(self) -> None:
        tracks = discover_tracks(self.music_folders)
        self.player.set_library(tracks)
        self.track_list.delete(0, tk.END)
        for track in tracks:
            self.track_list.insert(tk.END, track.stem)
        self.track_count.configure(text=f"{len(tracks)} TRACKS")
        if tracks:
            folders = ", ".join(folder.name for folder in self.music_folders)
            self.library_hint.configure(text=f"Scanning {folders}")
            if self.player.current_index is not None:
                self.track_list.selection_set(self.player.current_index)
        else:
            self.library_hint.configure(text="No supported audio found. Add a folder to get started.")
        self._set_status(f"{len(tracks)} tracks in your library")

    def add_folder(self) -> None:
        selected = filedialog.askdirectory(title="Add a music folder")
        if not selected:
            return
        folder = Path(selected).expanduser().resolve()
        if folder not in self.music_folders:
            self.music_folders.append(folder)
        self.refresh_library()

    def _show_track_menu(self, event: tk.Event) -> str:
        index = self.track_list.nearest(event.y)
        bounds = self.track_list.bbox(index)
        if bounds is None or not bounds[1] <= event.y <= bounds[1] + bounds[3]:
            return "break"
        self.track_list.selection_clear(0, tk.END)
        self.track_list.selection_set(index)
        self.track_list.activate(index)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(
            label="Edit",
            command=lambda selected_index=index: self.edit_track(
                self.player.tracks[selected_index]
            ),
        )
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def edit_track(self, path: Path) -> None:
        if path.suffix.casefold() != ".mp3":
            messagebox.showinfo(
                "Edit track",
                "Tag and embedded lyric editing is currently available for MP3 files.",
                parent=self.root,
            )
            return

        try:
            from mutagen import File as MutagenFile

            metadata = MutagenFile(path, easy=True)
            tags = (
                metadata.tags
                if metadata is not None and metadata.tags is not None
                else {}
            )
            initial_title = (tags.get("title") or [path.stem])[0]
            initial_artist = (tags.get("artist") or [""])[0]
            lyrics, synchronized = read_track_lyrics(path)
            lyrics_text = (
                format_lrc(lyrics)
                if synchronized
                else "\n".join(line.text for line in lyrics)
            )
        except (OSError, RuntimeError, AttributeError, TypeError) as error:
            messagebox.showerror("Could not read track", str(error), parent=self.root)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit track — {path.name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=BG)
        dialog.geometry("620x560")
        dialog.minsize(480, 420)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(5, weight=1)

        tk.Label(dialog, text="FILE NAME / TITLE", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=22, pady=(20, 6)
        )
        title_entry = tk.Entry(
            dialog, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=("TkDefaultFont", 11), borderwidth=0,
        )
        title_entry.grid(row=1, column=0, sticky="ew", padx=22, ipady=9)
        title_entry.insert(0, initial_title)

        tk.Label(dialog, text="ARTIST", bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).grid(
            row=2, column=0, sticky="w", padx=22, pady=(14, 6)
        )
        artist_entry = tk.Entry(
            dialog, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
            font=("TkDefaultFont", 11), borderwidth=0,
        )
        artist_entry.grid(row=3, column=0, sticky="ew", padx=22, ipady=9)
        artist_entry.insert(0, initial_artist)

        lyrics_header = tk.Frame(dialog, bg=BG)
        lyrics_header.grid(row=4, column=0, sticky="ew", padx=22, pady=(16, 6))
        lyrics_header.grid_columnconfigure(0, weight=1)
        tk.Label(
            lyrics_header, text="LYRICS (.LRC FORMAT OR PLAIN TEXT)",
            bg=BG, fg=MUTED, font=("TkDefaultFont", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self._button(
            lyrics_header, "Open .lrc", lambda: self._insert_lrc_file(dialog, lyrics_editor),
            subtle=True,
        ).grid(row=0, column=1, sticky="e")

        lyrics_frame = tk.Frame(dialog, bg=PANEL)
        lyrics_frame.grid(row=5, column=0, sticky="nsew", padx=22)
        lyrics_frame.grid_rowconfigure(0, weight=1)
        lyrics_frame.grid_columnconfigure(0, weight=1)
        lyrics_editor = tk.Text(
            lyrics_frame, bg=PANEL, fg=TEXT, insertbackground=TEXT,
            selectbackground="#33402c", wrap="word", relief="flat",
            borderwidth=0, font=("TkFixedFont", 10), padx=10, pady=10,
        )
        lyrics_editor.grid(row=0, column=0, sticky="nsew")
        lyrics_editor.insert("1.0", lyrics_text)
        editor_scroll = tk.Scrollbar(
            lyrics_frame, orient="vertical", command=lyrics_editor.yview
        )
        editor_scroll.grid(row=0, column=1, sticky="ns")
        lyrics_editor.configure(yscrollcommand=editor_scroll.set)

        actions = tk.Frame(dialog, bg=BG)
        actions.grid(row=6, column=0, sticky="e", padx=22, pady=18)
        self._button(actions, "Cancel", dialog.destroy, subtle=True).pack(side="right")
        self._button(
            actions,
            "Save changes",
            lambda: self._save_track_edits(
                dialog, path, title_entry.get(), artist_entry.get(),
                lyrics_editor.get("1.0", "end-1c"),
            ),
            primary=True,
        ).pack(side="right", padx=(0, 10))
        title_entry.focus_set()

    def _insert_lrc_file(self, dialog: tk.Toplevel, editor: tk.Text) -> None:
        selected = filedialog.askopenfilename(
            parent=dialog,
            title="Attach lyrics",
            filetypes=[("LRC lyrics", "*.lrc"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            content = Path(selected).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Could not open lyrics", str(error), parent=dialog)
            return
        editor.delete("1.0", tk.END)
        editor.insert("1.0", content)

    def _save_track_edits(
        self,
        dialog: tk.Toplevel,
        path: Path,
        title: str,
        artist: str,
        lyrics_text: str,
    ) -> None:
        is_current = self.player.current_track == path
        was_playing = self.player.is_playing
        if is_current:
            self.player.stop()
            try:
                pygame.mixer.music.unload()
            except pygame.error:
                pass
        try:
            destination = save_mp3_metadata(
                path, title=title, artist=artist, lrc_text=lyrics_text
            )
        except (OSError, RuntimeError, ValueError) as error:
            if is_current:
                self._reload_after_edit(path, was_playing)
            messagebox.showerror("Could not save track", str(error), parent=dialog)
            return

        dialog.destroy()
        self.refresh_library()
        if is_current:
            self._reload_after_edit(destination, was_playing)
        self._set_status(f"Updated {destination.name}")

    def _reload_after_edit(self, path: Path, was_playing: bool) -> None:
        try:
            index = self.player.tracks.index(path)
            self.player.play_index(index)
            if not was_playing:
                self.player.pause()
        except (ValueError, pygame.error, OSError, RuntimeError) as error:
            self._set_status(f"Track metadata saved, but playback could not resume: {error}", error=True)
        self._displayed_track = None
        self._sync_displayed_track()
        self._render_lyrics()
        self._update_play_button()

    def _play_selection(self, _event: tk.Event | None = None) -> None:
        selection = self.track_list.curselection()
        if selection:
            self._play_index(selection[0])

    def _play_index(self, index: int) -> None:
        try:
            self.player.play_index(index)
        except (pygame.error, OSError, RuntimeError, ValueError, IndexError) as error:
            self._set_status(f"Could not play track: {error}", error=True)
            return
        track = self.player.current_track
        self._displayed_track = None
        self._sync_displayed_track()
        if track is not None and not self.player.lyrics:
            self._request_track_lyrics(track)
        self._set_status(f"Playing {track.name if track else 'track'}")
        self._update_play_button()

    def toggle_play(self) -> None:
        try:
            self.player.toggle_play_pause()
        except (pygame.error, RuntimeError) as error:
            self._set_status(str(error), error=True)
            return
        if self.player.current_track is not None:
            self._update_play_button()
            self._set_status("Playing" if self.player.is_playing else "Paused")

    def next_track(self) -> None:
        self._change_track(self.player.next_track)

    def previous_track(self) -> None:
        self._change_track(self.player.previous_track)

    def _change_track(self, action) -> None:
        try:
            action()
        except (pygame.error, OSError, RuntimeError, ValueError, IndexError) as error:
            self._set_status(f"Could not change track: {error}", error=True)
            return
        self._displayed_track = None
        self._sync_displayed_track()
        self._update_play_button()

    def toggle_shuffle(self) -> None:
        self.shuffle_enabled = not self.shuffle_enabled
        self.player.shuffle = self.shuffle_enabled
        self.shuffle_button.configure(
            fg=ACCENT if self.shuffle_enabled else TEXT,
            bg="#29351f" if self.shuffle_enabled else PANEL_LIGHT,
        )
        self._set_status("Shuffle on" if self.shuffle_enabled else "Shuffle off")

    def toggle_repeat(self) -> None:
        modes = ("off", "all", "one")
        self.repeat_mode = modes[(modes.index(self.repeat_mode) + 1) % len(modes)]
        self.player.repeat_mode = self.repeat_mode
        labels = {"off": "↻", "all": "↻ all", "one": "↻ 1"}
        self.repeat_button.configure(
            text=labels[self.repeat_mode],
            fg=ACCENT if self.repeat_mode != "off" else TEXT,
        )
        self._set_status(f"Repeat {self.repeat_mode}")

    def toggle_lyrics_panel(self) -> None:
        if self.lyrics_panel is None:
            return
        self._lyrics_visible = not self._lyrics_visible
        if self._lyrics_visible:
            self.lyrics_panel.grid()
        else:
            self.lyrics_panel.grid_remove()
        self.lyric_button.configure(
            fg=ACCENT if self._lyrics_visible else TEXT,
            bg="#29351f" if self._lyrics_visible else PANEL_LIGHT,
        )
        self._render_lyrics()

    def _edit_current_lyrics(self) -> None:
        if self.player.current_track is None:
            messagebox.showinfo(
                "Lyrics", "Choose an MP3 from your library before editing lyrics.",
                parent=self.root,
            )
            return
        self.edit_track(self.player.current_track)

    def _render_lyrics(self) -> None:
        if self.lyrics_view is None or not self.lyrics_view.winfo_exists():
            return

        self.lyrics_view.configure(state="normal")
        self.lyrics_view.delete("1.0", tk.END)
        if self._lyrics:
            for line in self._lyrics:
                self.lyrics_view.insert(tk.END, f"{line.text or '♪'}\n", "line")
            track = self.player.current_track
            self.lyrics_title.configure(
                text=(
                    f"{track.stem if track else 'LYRICS'}  •  "
                    f"{'SYNCED' if self.player.lyrics_synced else 'PLAIN'} LYRICS"
                )
            )
        else:
            if self.player.current_track is None:
                prompt = "Choose a track to view its lyrics."
                self.lyrics_title.configure(text="LYRICS")
            else:
                if self.player.current_track.suffix.casefold() == ".mp3":
                    prompt = (
                        "No embedded lyrics or matching .lrc file was found.\n\n"
                        "Choose “Add or edit lyrics” to attach lyrics to the MP3."
                    )
                else:
                    prompt = (
                        "No matching .lrc file was found for this track.\n\n"
                        "Choose an MP3 to add embedded lyrics."
                    )
                self.lyrics_title.configure(text="LYRICS NOT FOUND")
            self.lyrics_view.insert(tk.END, prompt, "line")
        self.lyrics_view.configure(state="disabled")
        if self._lyrics:
            self._highlight_lyric(self.player.active_lyric_index())
        elif self.player.current_track is None:
            self.current_lyric.configure(text="Select a track to view lyrics")
        else:
            self.current_lyric.configure(text="No lyrics found for this track")

    def _seek_to_lyric(self, event: tk.Event) -> str:
        if (
            not self._lyrics
            or not self.player.lyrics_synced
            or self.player.current_track is None
            or self.lyrics_view is None
        ):
            return "break"
        index = int(self.lyrics_view.index(f"@{event.x},{event.y}").split(".")[0]) - 1
        if 0 <= index < len(self._lyrics):
            self.player.seek(self.player.lyric_position(index))
            if self.player.is_paused:
                self.player.is_paused = False
                self.player.play()
            self._update_play_button()
        return "break"

    def _begin_seek(self, _event: tk.Event) -> None:
        self._seeking = True

    def _finish_seek(self, _event: tk.Event) -> None:
        self._seeking = False
        if self.player.duration is not None:
            self.player.seek(float(self.seek_scale.get()))

    def _seek_changed(self, _value: str) -> None:
        if self._seeking:
            self.elapsed_label.configure(text=format_time(float(self.seek_scale.get())))

    def _volume_changed(self, value: str) -> None:
        self.player.set_volume(float(value) / 100)

    def _update_play_button(self) -> None:
        self.play_button.configure(text="Ⅱ" if self.player.is_playing else "▶")

    def _draw_record(self, _event: tk.Event | None = None) -> None:
        self.cover.delete("all")
        width = max(1, self.cover.winfo_width())
        center_x, center_y = width // 2, 105
        radius = 92
        self.cover.create_oval(
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius,
            fill="#18201a", outline="#303a32", width=2,
        )
        for inset in (16, 29, 43, 57, 71):
            ring = radius - inset
            self.cover.create_oval(
                center_x - ring, center_y - ring,
                center_x + ring, center_y + ring,
                outline="#29342c",
            )
        self.cover.create_oval(
            center_x - 23, center_y - 23, center_x + 23, center_y + 23,
            fill=ACCENT, outline="",
        )
        initials = self.player.current_track.stem[:1].upper() if self.player.current_track else "♪"
        self.cover.create_text(
            center_x, center_y, text=initials, fill="#15200e",
            font=("TkDefaultFont", 15, "bold"),
        )

    def _tick(self) -> None:
        if self._closing:
            return
        self._process_download_messages()
        if not self._process_mpris_commands():
            return
        try:
            background_message = self._background_messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self._set_status(background_message, error=True)
        self._sync_displayed_track()
        if self.player.repeat_mode != self.repeat_mode:
            self.repeat_mode = self.player.repeat_mode
            labels = {"off": "↻", "all": "↻ all", "one": "↻ 1"}
            self.repeat_button.configure(
                text=labels[self.repeat_mode],
                fg=ACCENT if self.repeat_mode != "off" else TEXT,
            )
        if self.player.shuffle != self.shuffle_enabled:
            self.shuffle_enabled = self.player.shuffle
            self.shuffle_button.configure(
                fg=ACCENT if self.shuffle_enabled else TEXT,
                bg="#29351f" if self.shuffle_enabled else PANEL_LIGHT,
            )
        position = self.player.position
        duration = self.player.duration
        self.elapsed_label.configure(text=format_time(position))
        self.duration_label.configure(text=format_time(duration))
        self.seek_scale.configure(
            to=duration if duration and duration > 0 else 1,
            state="normal" if duration else "disabled",
        )
        if not self._seeking:
            self.seek_scale.set(position)
        if abs(self.volume_scale.get() - self.player.volume * 100) >= 1:
            self.volume_scale.set(self.player.volume * 100)

        active_index = self.player.active_lyric_index()
        if active_index != self._last_lyric_index:
            self._highlight_lyric(active_index)
            self._last_lyric_index = active_index
        if self.player.track_finished():
            if self.repeat_mode == "one":
                self.player.seek(0)
                self.player.play()
            elif self.repeat_mode == "all" or self.shuffle_enabled:
                self.next_track()
            elif self.player.current_index is not None and self.player.current_index + 1 < len(self.player.tracks):
                self.next_track()
            else:
                self.player.stop()
                self._update_play_button()
        self.root.after(250, self._tick)

    def _process_download_messages(self) -> None:
        while True:
            try:
                kind, payload = self._download_messages.get_nowait()
            except queue.Empty:
                return

            if kind == "progress":
                progress = payload
                if not isinstance(progress, dict):
                    continue
                status = progress.get("status")
                if status == "downloading":
                    total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
                    downloaded = progress.get("downloaded_bytes", 0)
                    if isinstance(total, (int, float)) and total > 0:
                        self.download_progress.stop()
                        self.download_progress.configure(mode="determinate")
                        self.download_progress["value"] = min(100, downloaded * 100 / total)
                        percent = self.download_progress["value"]
                        self.download_status.configure(
                            text=f"Downloading audio… {percent:.0f}%", fg=MUTED
                        )
                    else:
                        self.download_status.configure(text="Downloading audio…", fg=MUTED)
                elif status == "finished":
                    self.download_status.configure(text="Converting audio to MP3…", fg=MUTED)
                continue

            self._download_active = False
            self.download_progress.stop()
            self.download_progress.configure(mode="determinate")
            self.download_button.configure(
                state="normal", text="↓  Paste link & download"
            )
            if kind == "complete" and isinstance(payload, Path):
                self.download_progress["value"] = 100
                self.download_status.configure(
                    text=f"Saved to {payload.name}",
                    fg=ACCENT,
                )
                self.refresh_library()
                self._set_status(f"Downloaded {payload.name}")
            elif kind == "error":
                self.download_progress["value"] = 0
                self.download_status.configure(text=str(payload), fg="#ff8b82")
                self._set_status(f"Download failed: {payload}", error=True)

    def _process_mpris_commands(self) -> bool:
        while True:
            try:
                command, value = self._mpris_commands.get_nowait()
            except queue.Empty:
                return True
            try:
                if command == "play":
                    self.player.play()
                elif command == "pause":
                    self.player.pause()
                elif command == "toggle":
                    self.player.toggle_play_pause()
                elif command == "stop":
                    self.player.stop()
                elif command == "next":
                    self.player.next_track()
                elif command == "previous":
                    self.player.previous_track()
                elif command == "seek" and isinstance(value, (int, float)):
                    self.player.seek(float(value))
                elif command == "shuffle":
                    self.player.shuffle = bool(value)
                elif command == "volume" and isinstance(value, (int, float)):
                    self.player.set_volume(float(value))
                elif command == "repeat" and value in {"off", "all", "one"}:
                    self.player.repeat_mode = str(value)
                elif command == "raise":
                    self.root.deiconify()
                    self.root.lift()
                    self.root.focus_force()
                elif command == "quit":
                    self.close()
                    return False
                self._sync_displayed_track()
                self._update_play_button()
            except (pygame.error, OSError, RuntimeError, ValueError) as error:
                self._set_status(f"System media command failed: {error}", error=True)

    def _sync_displayed_track(self) -> None:
        track = self.player.current_track
        if track == self._displayed_track:
            return
        self._displayed_track = track
        if track is None:
            self.track_title.configure(text="Pick something to play")
            self.track_subtitle.configure(text="Your local library, ready when you are.")
            self._lyrics = []
            self._render_lyrics()
            self._draw_record()
            return

        metadata = self.player.track_metadata
        title = metadata.get("title", track.stem)
        subtitle = " • ".join(
            value for value in (metadata.get("artist"), metadata.get("album")) if value
        ) or str(track.parent)
        self.track_title.configure(text=title)
        self.track_subtitle.configure(text=subtitle)
        if self.player.current_index is not None:
            self.track_list.selection_clear(0, tk.END)
            self.track_list.selection_set(self.player.current_index)
            self.track_list.see(self.player.current_index)
        self._lyrics = self.player.lyrics
        self._render_lyrics()
        self._last_lyric_index = None
        self._draw_record()

    def _highlight_lyric(self, index: int | None) -> None:
        if self.lyrics_view is None or not self.lyrics_view.winfo_exists():
            return
        self.lyrics_view.configure(state="normal")
        self.lyrics_view.tag_remove("active", "1.0", tk.END)
        if (
            self.player.lyrics_synced
            and index is not None
            and index < len(self._lyrics)
        ):
            start = f"{index + 1}.0"
            end = f"{index + 1}.end"
            self.lyrics_view.tag_add("active", start, end)
            self.lyrics_view.see(start)
            self.current_lyric.configure(text=self._lyrics[index].text or "♪")
        elif self._lyrics and not self.player.lyrics_synced:
            self.current_lyric.configure(text="♪  Unsynchronized lyrics")
        elif not self._lyrics:
            self.current_lyric.configure(text="No lyrics attached — open Lyric to add them")
        self.lyrics_view.configure(state="disabled")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.header_status.configure(
            text=message.upper(),
            fg="#ff8b82" if error else MUTED,
        )

    def _theme_palette(self, theme: str) -> dict[str, str]:
        if theme == "light":
            return {
                BG: "#f3f5f2",
                PANEL: "#ffffff",
                PANEL_LIGHT: "#e5eae5",
                ACCENT: "#527c28",
                TEXT: "#202720",
                MUTED: "#68746a",
                LINE: "#c8d1c8",
                "#29351f": "#dce8d1",
                "#33402c": "#d4e2c8",
                "#303a32": "#bcc9bc",
                "#18201a": "#e7ece6",
                "#29342c": "#dce3da",
                "#15200e": "#eff5e8",
                "#10140d": "#f3f5f2",
                "#d4ff91": "#dce8d1",
                "#28312c": "#d4e2c8",
                "#ff8b82": "#b3261e",
            }
        return {
            BG: "#0d1010",
            PANEL: "#151a19",
            PANEL_LIGHT: "#1d2421",
            ACCENT: "#c3f27a",
            TEXT: "#f1f3ed",
            MUTED: "#89918a",
            LINE: "#29312d",
            "#29351f": "#29351f",
            "#33402c": "#33402c",
            "#303a32": "#303a32",
            "#18201a": "#18201a",
            "#29342c": "#29342c",
            "#15200e": "#15200e",
            "#10140d": "#10140d",
            "#d4ff91": "#d4ff91",
            "#28312c": "#28312c",
            "#ff8b82": "#ff8b82",
        }

    def _theme_button_label(self) -> str:
        selected = self.theme_preference.title()
        return f"Theme: {selected}"

    def toggle_theme(self) -> None:
        modes = ("system", "dark", "light")
        new_preference = modes[(modes.index(self.theme_preference) + 1) % len(modes)]
        try:
            save_theme_preference(new_preference)
        except (OSError, RuntimeError, ValueError) as error:
            self._set_status(f"Could not save theme preference: {error}", error=True)
            return
        self.theme_preference = new_preference
        self.theme_name = system_theme() if new_preference == "system" else new_preference
        self.theme_colors = self._theme_palette(self.theme_name)
        self._apply_theme()
        self.theme_button.configure(text=self._theme_button_label())

    def _apply_theme(self) -> None:
        light_colors = self._theme_palette("light")
        color_map: dict[str, str] = {}
        for dark_color, target_color in self.theme_colors.items():
            color_map[dark_color] = target_color
            color_map[light_colors[dark_color]] = target_color

        def update_widget(widget: tk.Widget) -> None:
            options: dict[str, str] = {}
            for option in (
                "bg", "fg", "activebackground", "activeforeground",
                "disabledforeground", "insertbackground", "selectbackground",
                "selectforeground", "troughcolor", "highlightbackground",
            ):
                try:
                    value = str(widget.cget(option))
                except tk.TclError:
                    continue
                if value in color_map:
                    options[option] = color_map[value]
            if options:
                try:
                    widget.configure(**options)
                except tk.TclError:
                    pass
            if isinstance(widget, tk.Text):
                widget.tag_configure("active", foreground=self.theme_colors[ACCENT])
                widget.tag_configure("line", foreground=self.theme_colors[MUTED])
            for child in widget.winfo_children():
                update_widget(child)

        update_widget(self.root)
        style = ttk.Style(self.root)
        style.configure(
            "TProgressbar",
            background=self.theme_colors[ACCENT],
            troughcolor=self.theme_colors[PANEL_LIGHT],
        )
        self._draw_record()

    def _start_mpris(self) -> None:
        def run_service() -> None:
            try:
                from MPRIS import start_service

                start_service(
                    self.player,
                    lambda command, value=None: self._mpris_commands.put((command, value)),
                )
            except (ImportError, OSError, RuntimeError) as error:
                if not self._closing:
                    self._background_messages.put(f"MPRIS unavailable: {error}")

        threading.Thread(target=run_service, name="tmusic-mpris", daemon=True).start()

    def _start_system_tray(self) -> None:
        try:
            from system_tray import create_system_tray

            self._tray_icon = create_system_tray(
                lambda: self._mpris_commands.put(("raise", None)),
                lambda: self._mpris_commands.put(("quit", None)),
            )
            self._tray_icon.run_detached()
            self._tray_icon.visible = True
        except Exception as error:
            self._tray_icon = None
            self._tray_error = str(error)
            self._background_messages.put(f"System tray unavailable: {error}")

    def _hide_window(self, _event: tk.Event | None = None) -> str:
        self.root.withdraw()
        return "break"

    def _on_close(self) -> None:
        if platform.system() == "Linux":
            if self._tray_icon is not None:
                self.root.withdraw()
                return
            messagebox.showwarning(
                "System tray unavailable",
                "Tmusic cannot stay hidden because its tray menu did not start. "
                "The app will now exit.\n\n"
                f"{self._tray_error or 'No tray backend is available.'}",
                parent=self.root,
            )
        self.close()

    def close(self) -> None:
        self._closing = True
        self.player.stop()
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TmusicApp(root)
    root.mainloop()
