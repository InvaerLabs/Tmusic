# Changelog

## Version 3.0

- Improved MPRIS lifecycle and deferred seek notifications until the player
  applies a requested seek.
- Added platform-specific build imports so Linux, Windows, and macOS binaries
  include only their native media-control integration.
- Added persistent library-folder management, a cover-art visibility setting,
  an About section, and a GitHub release update check.
- Added embedded album artwork with a playback-only spinning-record treatment
  and refreshed the Stars theme with softer, playful colors.
- Kept decoded cover artwork small and limited to the currently playing track
  to reduce avoidable memory use.

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
