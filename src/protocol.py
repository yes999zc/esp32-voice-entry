"""Xiaozhi WebSocket message shapes (protocol v1, binary = raw Opus)."""
import json

PROTOCOL_VERSION = 1


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def hello_reply(session_id: str, sample_rate: int, frame_ms: int) -> str:
    return _dumps({
        "type": "hello",
        "transport": "websocket",
        "session_id": session_id,
        "audio_params": {
            "format": "opus",
            "sample_rate": sample_rate,
            "channels": 1,
            "frame_duration": frame_ms,
        },
    })


def stt(text: str, session_id: str) -> str:
    return _dumps({"session_id": session_id, "type": "stt", "text": text})


def tts_start(session_id: str) -> str:
    return _dumps({"session_id": session_id, "type": "tts", "state": "start"})


def tts_stop(session_id: str) -> str:
    return _dumps({"session_id": session_id, "type": "tts", "state": "stop"})


def tts_sentence(text: str, session_id: str) -> str:
    return _dumps({"session_id": session_id, "type": "tts",
                   "state": "sentence_start", "text": text})


def llm_emotion(emotion: str, session_id: str) -> str:
    return _dumps({"session_id": session_id, "type": "llm", "emotion": emotion})


def mcp_tool_call(name: str, arguments: dict, msg_id: int = 1) -> str:
    """MCP-over-WS call. The firmware parses payload as plain JSON-RPC 2.0 and
    does not require an `initialize` handshake before `tools/call`."""
    return _dumps({
        "type": "mcp",
        "payload": {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    })


def mcp_initialize(capabilities: dict, msg_id: int = 0) -> str:
    """MCP initialize. `capabilities.vision.url` is where the firmware POSTs
    photos when its `self.camera.take_photo` tool runs (mcp_server.cc
    ParseCapabilities -> camera->SetExplainUrl)."""
    return _dumps({
        "type": "mcp",
        "payload": {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "initialize",
            "params": {"capabilities": capabilities},
        },
    })


def notify(audio_url: str, text: str, start_ms: int = 0) -> str:
    """Asynchronous one-way voice notification (firmware docs/notify.md).

    Only honoured while the device is Idle; it never opens the mic. The audio must
    be a single-stream mono Ogg Opus file served over http(s).
    """
    return _dumps({
        "type": "notify",
        "audio_url": audio_url,
        "subtitles": [{"start_ms": start_ms, "text": text}],
    })
