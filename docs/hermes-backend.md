# Switching the backend to Hermes

Deferred by decision on 2026-10-21: do this when the board arrives, not before.
Until then `llm.provider: deepseek` in `config.yaml` keeps the server usable.

## Why

DeepSeek direct gives replies but no memory, no tool surface and no Telegram
side effects. Hermes' OpenAI-compatible API server gives all three, and the
pipeline already forwards `X-Hermes-Session-Id` so each device keeps its own
conversation.

## Step 1 - enable the API server (needs explicit approval, restarts gateway)

`~/.hermes/.env` currently has no `API_SERVER_*` keys. Append exactly two lines:

```
API_SERVER_ENABLED=true
API_SERVER_KEY=<random, generated on the spot>
```

- Key is mandatory: the server refuses to start when enabled without one.
- Defaults: `API_SERVER_HOST=127.0.0.1`, `API_SERVER_PORT=8642`. Loopback only;
  the device never talks to this port directly - our server proxies.
- Restart: `hermes gateway restart` (Telegram drops for ~10 s).
- Rollback: delete both lines, restart again. Nothing persists.

Verify:

```bash
curl -s -H "Authorization: Bearer $API_SERVER_KEY" \
     http://127.0.0.1:8642/v1/models | head
```

## Step 2 - point the server at it

`config.yaml`:

```yaml
llm:
  provider: hermes
  hermes:
    base_url: http://127.0.0.1:8642/v1
    model: default
```

`src/llm.py` reads `HERMES_API_KEY` from `~/.hermes/.env` when present and
otherwise sends `Bearer local`; set `HERMES_API_KEY` to the same value as
`API_SERVER_KEY` so the two agree.

## Step 3 - voice-shaped prompt

The system prompt in `config.yaml` is already written for speech: conclusion
first, at most three sentences, no markdown/URLs/lists. Do not reuse the
Telegram prompt. Voice turns should also refuse destructive actions
(delete/deploy/pay/SSH) in the prompt - there is no approval UI on the device.

## Step 4 - verify end to end

1. `python scripts/fake_device.py --wav <question.wav>` still works (text side).
2. Ask something only Hermes knows ("我刚才让你改了什么") - proves memory.
3. Ask it to turn on a light - proves the HA tool surface.
4. Check the transcript appears in the Hermes session with the device's
   session id, not mixed into the Telegram conversation.

## Control-plane token for `mcp_device.py`

The 4411 app rejects unauthenticated `/debug/*` calls. The stdio shim reads the
same secret as the voice server — env `ESP32_CONTROL_TOKEN` first, then the
file `~/.esp32-voice/control.token` (override the path with
`ESP32_CONTROL_TOKEN_FILE`) — and sends `Authorization: Bearer <token>` on
`POST /debug/tool`. If neither exists it reports a clear error instead of a 401.

Hermes does not inherit the shell that started the voice server, so when you
run the server with `ESP32_CONTROL_TOKEN` set, put the same variable in Hermes'
environment (or rely on the token file). Rotation: change the token, restart
the server, then restart Hermes; with the file source the shim also
picks up a rotated file on its next call.
