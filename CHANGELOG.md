# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.1] - 2026-11-06

### Added
- Desk Mate / 桌面伙伴 branding in the console, with the logo served from `/admin/logo.png`.
- Console, on-device screen and Desk Mate Cube previews in the README.
- A pytest GitHub Actions workflow (`.github/workflows/tests.yml`) running the full
  suite on Python 3.13 against `config.example.yaml`.

### Changed
- The macOS launchd entrypoint (`scripts/run_service.sh`) is part of the repository;
  restart with `launchctl kickstart -k gui/$(id -u)/com.bakey.esp32-voice`.
- Committed the redacted 2026-11-04 security audit (`docs/audit-2026-11-04.md`).
- `docs/HANDOFF.md` records the 2026-11-06 state check and the remaining security work.

## [0.2.0] - 2026-11-04

- Refreshed bilingual console with onboarding, device overview and remote wake.
- Added a bilingual introduction, deployment guide and AI-assisted setup prompts.
- Added device pairing and acknowledged remote wake for compatible firmware.

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
