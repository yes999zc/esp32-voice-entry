#!/bin/bash
set -u
BASE="http://127.0.0.1:4411"; TOK=$(cat ~/.esp32-voice/control.token)
EV="/Users/bakeyzhang/AI_Workspace/01_Code/projects/esp32-voice-entry/docs/tasks/abcd-views/evidence"
SVC="/tmp/esp32-voice-service.log"; UPURL="http://<nas-ip>:4411/debug/upload"
log() { echo "$*" | tee -a "$EV/curl-e2e.log" >&2; }
for n in 1 2 3 4 5; do
  ts=$(date '+%Y%m%d-%H%M%S'); before=$(wc -l < "$SVC")
  log "=== D retry $n $(date '+%F %T') ==="
  resp=$(curl -s -m 30 -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d '{"name":"self.screen.snapshot","arguments":{"url":"'"$UPURL"'","quality":90}}' "$BASE/debug/mcp")
  log "RESP $resp"
  path=""; for i in $(seq 1 60); do path=$(tail -n +$((before+1)) "$SVC" | grep -o '\[debug\] upload [0-9]* bytes -> [^ ]*snapshot-[^ ]*\.jpg' | tail -1 | sed 's/.*-> //'); [ -n "$path" ] && break; sleep 0.5; done
  if [ -z "$path" ]; then log "retry $n: FAILED (no upload)"; grep -n '\[mcp\] error' "$SVC" | tail -1 | while read -r l; do log "SVC $l"; done; sleep 2; continue; fi
  base=$(basename "$path"); out="$EV/view-D-extra$n-$ts.jpg"
  code=$(curl -s -m 15 -o "$out" -w '%{http_code}' -H "Authorization: Bearer $TOK" "$BASE/debug/photo/$base")
  log "retry $n: OK $path HTTP $code -> $out $(ls -l "$out" | awk '{print $5}') bytes sha256=$(shasum -a 256 "$out" | cut -d' ' -f1)"
  sleep 3
done
