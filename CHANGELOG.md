# Changelog

## Version 3.0

Version 3.0 moves the interface to a locally built HTML/Tailwind frontend and
keeps playback running in a background core while the WebView opens on demand.

- Added a standalone background playback core with authenticated local IPC.
  Closing the UI releases its WebView process without stopping playback; tray
  actions can reopen the UI with the current live player state.
- Added native MPRIS, Windows SMTC, and macOS Now Playing support alongside
  tray controls, with platform-specific media integrations in release builds.
- Reworked the player UI with embedded cover art, a spinning record, the Stars
  theme, library search, lyrics, and an MP3 metadata and cover editor.
- Added library-folder settings, update checks against GitHub releases, and
  theme and download preferences.
- Added manual 192, 256, and 320 kbps MP3 bitrate choices and a conversion
  progress status in the downloader.
- Added confirmation before closing the UI cancels an active download.
- Switched release builds to Nuitka standalone distributions with AppImage,
  Inno Setup, and DMG packaging for Linux, Windows, and macOS.
- Reduced repeated UI polling and unchanged payload work to lower avoidable
  resource use. Actual memory consumption varies by platform and library.

## Version 2.0

Tmusic 2.0 expands the original v1 player into a cross-platform music player
with integrated downloads, lyrics, and desktop controls.

- Added a downloader tab with progress and configurable download destination;
  downloads default to the user's Music folder.
- Improved Linux MPRIS integration for desktop media controls and track
  metadata, including duration and lyrics where supported.
- Added MP3 title/artist editing and support for embedding synchronized or
  plain lyrics in MP3 ID3 tags.
- Added automatic display of embedded MP3 lyrics and matching `.lrc` sidecars
  in an inline, show/hide lyrics panel.
- Updated shuffle to play each library track once per round before reshuffling.
- Added System, Dark, and Light appearance options and persistent preferences.
- Added Linux, Windows, and macOS release builds, plus updated installation
  and usage documentation.

## Version 1.0

The original v1 release provided the basic local music-player experience.
Version 2.0 retains local playback and builds on it with the features listed
above.
