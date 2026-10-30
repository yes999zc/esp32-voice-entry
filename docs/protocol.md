# Xiaozhi WebSocket protocol (device side, v1)

Source: `78/xiaozhi-esp32` `docs/websocket_zh.md`, checked 2026-10-21.

## Handshake

Device connects with headers `Authorization`, `Protocol-Version`, `Device-Id`, `Client-Id`,
then sends:

```json
{
  "type": "hello",
  "version": 1,
  "features": {"mcp": true},
  "transport": "websocket",
  "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}
}
```

Server must answer `{"type":"hello","transport":"websocket",...}` within 10 s or the device drops the channel.

## Audio

- Binary frames = raw Opus, one frame per `frame_duration` (60 ms).
- Server may declare its own `sample_rate` in the hello reply; the device resamples after decode.
- We keep 16 kHz mono both ways: 60 ms = 960 samples.

## Device to server

- `{"type":"listen","state":"start"|"stop"|"detect","mode":"auto"|"manual"|"realtime"}`
- `{"type":"abort","reason":"wake_word_detected"}` — stop TTS now
- `{"type":"mcp","payload":{...}}` — JSON-RPC for device-local tools

## Server to device

- `{"type":"stt","text":"..."}` — show transcript
- `{"type":"tts","state":"start"}` → binary frames → `{"type":"tts","state":"stop"}`
- `{"type":"tts","state":"sentence_start","text":"..."}` — subtitle line
- `{"type":"llm","emotion":"happy"}` — avatar only, optional
- `{"type":"system","command":"reboot"}`

## Consequences for the server

1. TTS audio must be sliced into exact 60 ms Opus frames, otherwise playback stutters.
2. `abort` arrives while we are streaming; cancel the TTS task, close the turn, go back to listening.
3. In `auto` mode the device streams continuously; segmenting is the server's job (VAD).
4. Device ignores inbound audio while it believes it is listening, so `tts start` must precede frames.
