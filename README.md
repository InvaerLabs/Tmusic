# Tmusic - *by* **Invaer Labs**

![Logo](Logo.jpeg)

Tmusic is a lightweight, open-source desktop music player and downloader built with Python and Tkinter. Designed for music lovers, gamers, and power users, it offers a distraction-free offline listening experience across Linux, Windows, and macOS. 

Unlike resource-heavy streaming platforms, Tmusic focuses on maximum performance and flexibility, allowing users to build a truly customized offline library.

## Key Advantages

* **Lightweight Local Playback:** Tmusic keeps playback local and avoids loading the downloader and cover-image decoding until needed. Memory use varies by platform, audio backend, and selected artwork.
* **Unrestricted Audio Library:** Seamlessly download and play audio content that is typically unavailable on mainstream streaming platforms like Spotify, such as custom Anime Music Videos (AMVs), tracks with unique character voiceovers, custom beats, and independent remixes.

## Features

* **Multi-Format Playback:** Automatically scans and indexes MP3, FLAC, OGG, and WAV tracks from multiple user-defined local directories.
* **Built-in Audio Downloader:** Downloads and auto-converts online audio links directly to your local storage at 192 kbps MP3 format. Powered by PyAV's bundled media libraries and LAME encoding, requiring no external system FFmpeg executable.
* **Synchronized Inline Lyrics:** Supports plain and synchronized lyrics using embedded ID3 tags or matching .lrc sidecar files. Timestamps are fully interactive, enabling click-to-seek functionality.
* **Metadata and ID3 Tag Editor:** Right-click any track in the library to edit the title, artist name, rename the physical audio file, or embed custom lyrics.
* **Album Artwork:** Displays embedded cover art in a sleeve-and-record view with a gentle, playback-only record animation. Artwork can be hidden in Settings.
* **Flexible UI Themes:** Features a clean, modern user interface that dynamically switches between System, Light, Dark, and a soft, starry night-sky Stars theme.
* **Library and Updates:** Add or remove scanned folders, choose whether to show artwork, and check GitHub for the latest release from Settings.
* **Native Desktop Integration:** Supports Linux MPRIS, Windows System Media Transport Controls (SMTC), macOS Now Playing, and a Linux system tray menu. Each release build bundles only its platform's media-control integration.

## Installation

### From Pre-built Releases
Download the latest package for your specific operating system and CPU architecture from the Releases page:

* **Windows:** Extract `Tmusic-Windows-x86_64.zip` or `Tmusic-Windows-arm64.zip` and run `Tmusic.exe`.
* **Linux:** Extract `Tmusic-Linux-x86_64.tar.gz` or `Tmusic-Linux-arm64.tar.gz`, grant execution permissions using `chmod +x Tmusic`, and execute `./Tmusic`.
* **macOS:** Extract `Tmusic-macOS-x86_64.zip` or `Tmusic-macOS-arm64.zip` and launch `Tmusic.app`.

### From Source (Development)
To run the project locally or contribute to development, ensure you have Python installed, then execute the following commands:

```bash
# Clone the repository
git clone https://github.com/InvaerLabs/Tmusic.git
cd Tmusic

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Why you choose Tmusic?

Imagine you are exploring YouTube and come across an AMV (Anime Music Video) that you absolutely love. Typically, creators edit the music in these AMVs by adding extra beats or incorporating anime character voiceovers. You fall in love with a video like this, but you can't download it for free, nor can you find it on Spotify. The journey of Tmusic began precisely to solve this problem. All you have to do is copy the link to your favorite video, paste it into our Tmusic app, and that's it—your track is ready for offline playback.

Now, imagine another scenario: you love listening to music while gaming, but desktop music applications are usually heavy and consume a lot of RAM, which disrupts your gaming experience. Our Tmusic app has no such issues. We built this app using a lightweight Python script that absorbs very little RAM (less than 70MB), ensuring a seamless experience during your gaming sessions


## Keyboard Shortcuts

* **Space:** Play / Pause playback
* **Ctrl + Left Arrow:** Previous track
* **Ctrl + Right Arrow:** Next track
* **Super + Q (Linux):** Hide window to system tray (keeps playback active)

## Architecture and File Structure

* `main.py`: Core entry point of the application.
* `player.py`: Handles audio playback logic and playlist states.
* `downloader.py`: Manages network requests, audio downloading, and conversion.
* `preferences.py`: Reads and writes configuration data (`settings.json`).
* `MPRIS.py`: Implements D-Bus and MPRIS protocol controls for Linux desktops.
* `SMTC.py`: Implements Windows System Media Transport Controls.
* `NowPlaying.py`: Implements macOS Now Playing and remote command controls.

## License

This project is licensed under the MIT License. See the [License](LICENSE) file for details.

## Screenshots

![Light](Screenshot1.png)


![Dark](Screenshot2.png)


![Star](Screenshot3.png)
