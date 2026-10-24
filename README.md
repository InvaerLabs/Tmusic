# Tmusic 2.0

Tmusic is a desktop music player and downloader built with Python, Tkinter,
and pygame. It runs on Linux, Windows, and macOS. Linux desktops can control
playback through MPRIS, including Hyprland/Caelestia widgets.

[See the v1-to-v2 changes in the changelog](./changelog.md).

## What you can do

- Scan folders for MP3, FLAC, OGG, and WAV tracks; create a library from
  multiple folders.
- Play, pause, seek, adjust volume, repeat a track or library, and shuffle
  through every track before starting a new shuffle round.
- Show or hide the inline lyrics panel with **Lyric**, without opening another
  window. Tmusic reads artist/title tags and embedded synchronized or plain
  lyrics from MP3 files and supports a matching `.lrc` sidecar.
- Right-click an MP3 in the library and choose **Edit** to change its title
  and artist, rename the audio file, paste lyrics, or attach an `.lrc` file.
  Saving stores lyrics inside the MP3 so they travel with the file.
- Download audio into `~/Music` by default, or pick another destination in the
  Download tab. The selected folder is remembered between launches.
- Switch between the detected system theme, dark theme, and light theme with
  the **Theme** button.
- Use Space for play/pause and Ctrl+Left / Ctrl+Right to change tracks.

Lyrics availability depends on the media file. A downloaded track does not
automatically include lyrics; add lyrics with **Edit** or open an `.lrc` file
from the edit dialog.

## Install from a release

Download the latest platform archive from the
[Tmusic Releases page](https://github.com/InvaerLabs/Tmusic/releases/latest).
Choose the archive matching your operating system and CPU architecture
(`x86_64` or `arm64`), then extract it:

- **Linux / Arch / Hyprland:** extract `Tmusic-Linux-x86_64.tar.gz` or
  `Tmusic-Linux-arm64.tar.gz`, then run
  `chmod +x Tmusic && ./Tmusic` from the extracted directory.
- **Windows:** extract `Tmusic-Windows-x86_64.zip` or
  `Tmusic-Windows-arm64.zip` and launch `Tmusic.exe`.
- **macOS:** extract `Tmusic-macOS-x86_64.zip` or
  `Tmusic-macOS-arm64.zip` and open `Tmusic.app`.

The release workflow builds native x86_64 and ARM64 packages for Linux,
Windows, and macOS. Tmusic uses pygame-ce, which provides the native
Windows ARM64 audio dependency.
FFmpeg must be installed separately for downloader audio conversion. Linux
MPRIS controls require the system D-Bus and GObject bindings.
On Linux, Tmusic also adds a tray menu with **Show Tmusic** and **Quit Tmusic**.
Closing the window hides it when the tray is available; use the tray's Quit
action to stop playback and exit. If no tray backend is available, closing
the window exits rather than leaving an inaccessible background process.

## Library, downloads, and settings

On first run, Tmusic scans `~/Music`. Use **Add folder** to include other
locations. Existing project `downloads/` files are also found when that
folder exists.

The Download tab saves MP3 audio at 192 kbps. Use **Choose** to select another
destination; Tmusic creates it when needed and adds it to the library scan.
Copy a supported video link, then click **Paste link & download** to read it
from the clipboard and start the download.
Only download content you have permission to use. Some services require
sign-in or anti-bot verification; Tmusic does not bypass those checks.

Preferences are stored in the platform's user configuration directory:

- Linux: `${XDG_CONFIG_HOME:-~/.config}/tmusic/settings.json`
- macOS: `~/Library/Application Support/tmusic/settings.json`
- Windows: `%APPDATA%\\tmusic\\settings.json`

The theme button cycles through **System**, **Dark**, and **Light**. System
theme detection uses the platform appearance setting where available.

## Lyrics and MP3 editing

For sidecar lyrics, place a file beside the audio with the same name and an
`.lrc` extension. The parser supports `[mm:ss.xx]` timestamps, multiple
timestamps per line, and `[offset:+/-milliseconds]`.

To save lyrics inside an MP3, right-click its library entry, select **Edit**,
then paste LRC/plain text or choose **Open .lrc**. Tmusic writes ID3 synchronized
and unsynchronized lyric frames. The **Lyric** button expands or hides the
lyrics panel in the player; synchronized lines can be clicked to seek. If no
embedded lyrics or matching sidecar exists, the panel offers an add-lyrics
prompt. Linux widgets that
support MPRIS `xesam:asText` can display embedded lyrics metadata.

On Linux, closing the player window or using **Super+Q** hides it while
playback and MPRIS remain active. Use the system tray's **Show Tmusic** menu
item or the MPRIS **Raise** command from a desktop widget to show it again. Use
the tray's **Quit Tmusic** item to exit. A Hyprland global binding can take
precedence over the in-app shortcut.

The release workflow builds and publishes platform archives when a `v2.0` or
`v2.0.*` tag is pushed. Manual workflow runs provide build artifacts through
GitHub Actions, while users should install the published binaries from the
Releases page.

## Development checks

```sh
python -m unittest discover -s tests -v
python -m compileall -q main.py player.py downloader.py preferences.py MPRIS.py
```
