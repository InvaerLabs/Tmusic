# Tmusic

A compact local music player built with Python, Tkinter, and pygame. It is
designed for Linux desktops such as Arch Linux with Hyprland: the interface
uses a dark, keyboard-friendly layout, and the optional MPRIS service exposes
playback controls to desktop widgets and media keys.

## Features

- Scan and play MP3, FLAC, OGG, and WAV files from one or more folders.
- Shuffle, repeat (off/all/one), previous/next, seeking, and volume controls.
- Follow synced `.lrc` files placed beside a track, or open one from the player.
  Click a lyric line to seek to its timestamp.
- Download audio from a video URL directly into the local music library.
- MPRIS 2 controls and metadata for compatible Linux desktop widgets and media
  keys, including play/pause, seeking, shuffle, repeat, volume, and track changes.
- Space toggles playback; Ctrl+Left and Ctrl+Right change tracks.

## Arch Linux setup

Install Tkinter and the audio runtime, then install the Python packages:

```sh
sudo pacman -S tk python ffmpeg python-dbus python-gobject
python -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Downloads go to `~/Music/` by default, and that folder is scanned as part of
the library. The Download tab's **Choose** button lets you select a different
destination; Tmusic saves that preference in
`${XDG_CONFIG_HOME:-~/.config}/tmusic/settings.json`. Existing project
`downloads/` files remain in the library when that folder exists. Use **Add
folder** to include other locations. Supported audio extensions are `.mp3`,
`.flac`, `.ogg`, and `.wav`.

For synchronized lyrics, name the file the same as the audio file, changing
the extension to `.lrc`. Standard `[mm:ss.xx]` timestamps, multiple
timestamps per line, and `[offset:+/-milliseconds]` are supported. The player
also publishes loaded LRC text as `xesam:asText` MPRIS metadata for widgets
that support displaying lyrics. Downloads do not automatically include lyric
files; add a matching `.lrc` sidecar or load one using **+ LRC**.

Open **Download** in the library sidebar, paste a video URL, choose the save
folder if needed, and select **Download audio**. Downloads are converted to
MP3 at 192 kbps; the library refreshes when a download completes. `ffmpeg` is
required for conversion. Only download content you have permission to use.
Some services restrict automated downloads or require account verification.
Tmusic does not bypass those checks; use the service's official download
option or a direct download you are authorized to access.

MPRIS uses the session D-Bus and runs alongside the player. It is optional:
without the D-Bus Python bindings, playback and downloads still work, but
desktop media controls will be unavailable. The Arch setup above exposes
`python-dbus` and `python-gobject` to the virtual environment.