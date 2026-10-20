from __future__ import annotations

import threading
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pygame

from downloader import Downloader
from preferences import load_download_directory, save_download_directory
from player import LyricLine, MusicPlayer, discover_tracks, format_time


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
        self._download_active = False
        self._displayed_track: Path | None = None

        self._build_ui()
        self.refresh_library()
        self._bind_shortcuts()
        self._start_mpris()
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self) -> None:
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
            text="Paste a video URL to save its audio to your library.",
            bg=PANEL, fg=MUTED, justify="left", wraplength=245,
            font=("TkDefaultFont", 9),
        ).grid(row=1, column=0, sticky="w", pady=(10, 18))
        self.download_url = tk.Entry(
            self.download_page, bg=PANEL_LIGHT, fg=TEXT, insertbackground=TEXT,
            relief="flat", borderwidth=0, font=("TkDefaultFont", 10),
        )
        self.download_url.grid(row=2, column=0, sticky="ew", ipady=10, pady=(0, 12))
        self.download_url.insert(0, "Paste URL")
        self.download_url.bind("<FocusIn>", self._clear_download_placeholder)
        self.download_button = self._button(
            self.download_page, "↓  Download audio", self.start_download, primary=True
        )
        self.download_button.grid(row=3, column=0, sticky="ew")
        self.download_progress = ttk.Progressbar(
            self.download_page, mode="determinate", maximum=100, style="TProgressbar"
        )
        self.download_progress.grid(row=4, column=0, sticky="ew", pady=(18, 8))
        self.download_status = tk.Label(
            self.download_page, text="MP3 • 192 kbps", bg=PANEL, fg=MUTED,
            anchor="w", justify="left", wraplength=245,
            font=("TkDefaultFont", 9),
        )
        self.download_status.grid(row=7, column=0, sticky="ew")
        tk.Label(
            self.download_page, text="SAVE TO", bg=PANEL, fg=TEXT,
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=5, column=0, sticky="w", pady=(24, 6))
        destination_row = tk.Frame(self.download_page, bg=PANEL)
        destination_row.grid(row=6, column=0, sticky="ew")
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

    def _clear_download_placeholder(self, _event: tk.Event) -> None:
        if self.download_url.get() == "Paste URL":
            self.download_url.delete(0, tk.END)

    def start_download(self) -> None:
        url = self.download_url.get().strip()
        if not url or url == "Paste URL":
            self.download_status.configure(text="Enter a video URL to download.", fg="#ff8b82")
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
        artwork_and_lyrics.grid_rowconfigure(1, weight=1)
        artwork_and_lyrics.grid_columnconfigure(0, weight=1)

        self.cover = tk.Canvas(
            artwork_and_lyrics, height=210, bg=BG,
            highlightthickness=0, borderwidth=0,
        )
        self.cover.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.cover.bind("<Configure>", self._draw_record)

        lyric_panel = tk.Frame(artwork_and_lyrics, bg=PANEL, padx=20, pady=16)
        lyric_panel.grid(row=1, column=0, sticky="nsew")
        lyric_panel.grid_rowconfigure(1, weight=1)
        lyric_panel.grid_columnconfigure(0, weight=1)
        lyric_head = tk.Frame(lyric_panel, bg=PANEL)
        lyric_head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        lyric_head.grid_columnconfigure(0, weight=1)
        tk.Label(
            lyric_head, text="LYRICS", bg=PANEL, fg=TEXT,
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.lyric_source = tk.Label(
            lyric_head, text="SYNCED LRC", bg=PANEL, fg=MUTED,
            font=("TkDefaultFont", 8, "bold"),
        )
        self.lyric_source.grid(row=0, column=1, sticky="e")

        lyrics_frame = tk.Frame(lyric_panel, bg=PANEL)
        lyrics_frame.grid(row=1, column=0, sticky="nsew")
        lyrics_frame.grid_rowconfigure(0, weight=1)
        lyrics_frame.grid_columnconfigure(0, weight=1)
        self.lyrics_view = tk.Text(
            lyrics_frame,
            bg=PANEL,
            fg=MUTED,
            insertbackground=ACCENT,
            selectbackground="#33402c",
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            font=("TkDefaultFont", 12),
            spacing1=5,
            spacing3=5,
            padx=2,
            pady=4,
            state="disabled",
        )
        self.lyrics_view.grid(row=0, column=0, sticky="nsew")
        lyric_scroll = tk.Scrollbar(
            lyrics_frame, orient="vertical", command=self.lyrics_view.yview,
            bg=PANEL_LIGHT, troughcolor=PANEL, relief="flat", borderwidth=0,
        )
        lyric_scroll.grid(row=0, column=1, sticky="ns")
        self.lyrics_view.configure(yscrollcommand=lyric_scroll.set)
        self.lyrics_view.tag_configure("active", foreground=ACCENT, font=("TkDefaultFont", 12, "bold"))
        self.lyrics_view.tag_configure("line", foreground=MUTED)
        self.lyrics_view.bind("<Button-1>", self._seek_to_lyric)

        self.current_lyric = tk.Label(
            lyric_panel, text="♪  Open a track to see its synced lyrics",
            bg=PANEL, fg=MUTED, anchor="w", font=("TkDefaultFont", 9, "italic"),
        )
        self.current_lyric.grid(row=2, column=0, sticky="ew", pady=(10, 0))

    def _build_transport(self) -> None:
        transport = tk.Frame(self.root, bg=PANEL, padx=28, pady=15)
        transport.grid(row=2, column=0, sticky="ew")
        transport.grid_columnconfigure(1, weight=1)

        left = tk.Frame(transport, bg=PANEL)
        left.grid(row=0, column=0, sticky="w")
        self._button(left, "＋  LRC", self.open_lyrics, subtle=True).pack(side="left")

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
        self.track_list.selection_clear(0, tk.END)
        self.track_list.selection_set(index)
        self.track_list.see(index)
        track = self.player.current_track
        if track is not None:
            self.track_title.configure(text=track.stem)
            self.track_subtitle.configure(text=str(track.parent))
        self._lyrics = self.player.lyrics
        self._render_lyrics()
        self._last_lyric_index = None
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
        if self.player.current_index is not None:
            self.track_list.selection_clear(0, tk.END)
            self.track_list.selection_set(self.player.current_index)
            self.track_list.see(self.player.current_index)
            self.track_title.configure(text=self.player.current_track.stem)
            self.track_subtitle.configure(text=str(self.player.current_track.parent))
            self._lyrics = self.player.lyrics
            self._render_lyrics()
            self._last_lyric_index = None
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

    def open_lyrics(self) -> None:
        if self.player.current_track is None:
            messagebox.showinfo("Open lyrics", "Select a track before loading its lyrics.", parent=self.root)
            return
        selected = filedialog.askopenfilename(
            title="Open synced lyrics",
            filetypes=[("LRC lyrics", "*.lrc"), ("All files", "*.*")],
            initialdir=self.player.current_track.parent,
        )
        if not selected:
            return
        try:
            self._lyrics = self.player.load_lyrics(Path(selected))
        except OSError as error:
            messagebox.showerror("Could not open lyrics", str(error), parent=self.root)
            return
        self.lyric_source.configure(text=Path(selected).name.upper())
        self._render_lyrics()
        self._last_lyric_index = None
        self._set_status(f"Loaded {len(self._lyrics)} lyric lines")

    def _render_lyrics(self) -> None:
        self.lyrics_view.configure(state="normal")
        self.lyrics_view.delete("1.0", tk.END)
        if self._lyrics:
            for line in self._lyrics:
                self.lyrics_view.insert(tk.END, f"{line.text or '♪'}\n", "line")
            self.lyric_source.configure(text="SYNCED LRC")
            self.current_lyric.configure(text="♪  Click a lyric line to jump to that moment")
        else:
            self.lyric_source.configure(text="NO LRC")
            self.lyrics_view.insert(
                tk.END,
                "No synced lyrics found.\n\nKeep an .lrc file next to the audio file, "
                "or use + LRC to open one.",
                "line",
            )
            self.current_lyric.configure(text="♪  Lyrics appear here in time with your music")
        self.lyrics_view.configure(state="disabled")

    def _seek_to_lyric(self, event: tk.Event) -> str:
        if not self._lyrics or self.player.current_track is None:
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
            self.download_button.configure(state="normal", text="↓  Download audio")
            if kind == "complete" and isinstance(payload, Path):
                self.download_progress["value"] = 100
                self.download_status.configure(
                    text=f"Saved to {payload.name}", fg=ACCENT
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
        self.lyrics_view.configure(state="normal")
        self.lyrics_view.tag_remove("active", "1.0", tk.END)
        if index is not None and index < len(self._lyrics):
            start = f"{index + 1}.0"
            end = f"{index + 1}.end"
            self.lyrics_view.tag_add("active", start, end)
            self.lyrics_view.see(start)
            self.current_lyric.configure(text=self._lyrics[index].text or "♪")
        elif not self._lyrics:
            self.current_lyric.configure(text="♪  Lyrics appear here in time with your music")
        self.lyrics_view.configure(state="disabled")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.header_status.configure(
            text=message.upper(),
            fg="#ff8b82" if error else MUTED,
        )

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

    def close(self) -> None:
        self._closing = True
        self.player.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TmusicApp(root)
    root.mainloop()
