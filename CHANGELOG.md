# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-10-28

First externally usable release.

### Added
- Voice entry over WebSocket/Opus: wake word, VAD, ASR, Hermes/DeepSeek LLM, Volc TTS, barge-in.
- Six-state expression protocol and server-side state/emotion cues.
- Mute truth on the server (`MuteState`, `/debug/mute`) with device-side sync and avatar mute trigger.
- Home Assistant light aliases and device tools (photo, volume, brightness, theme, status).
- A/B/C information views plus A idle Chromium-dino strip and D 480x150 dino game view.
- Hermes self-awareness: backend/version/model answers via `hermes_info`, and screen self-view via `show_screen`.
- Chinese UI font stack and paper/ink UI v2 visual language.

### Known limitations
- Dino game: pterodactyl uses one official frame (no wing animation); measured ~25 fps, 30 fps target not reached.
- Validated on one ESP32-S3 board and 2.4 GHz Wi-Fi only.
- Firmware is a fork build; see companion tag `v2.5.3-persona.1`.
