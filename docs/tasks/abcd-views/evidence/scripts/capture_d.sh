#!/bin/bash
set -u
BASE="http://127.0.0.1:4411"; TOK=$(cat ~/.esp32-voice/control.token)
EV="/Users/bakeyzhang/AI_Workspace/01_Code/projects/esp32-voice-entry/docs/tasks/abcd-views/evidence"
SVC="/tmp/esp32-voice-service.log"; UPURL="http://<nas-ip>:4411/debug/upload"
CMDLOG="$EV/curl-e2e.log"
log() { echo "$*" | tee -a "$CMDLOG" >&2; }
post() { local data="$1" resp; log "CMD $(date '+%F %T') curl -s ... -d '$data' $BASE/debug/mcp"; resp=$(curl -s -m 30 -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d "$data" "$BASE/debug/mcp"); log "RESP $resp"; echo "$resp"; }
shot() { local label="$1" out="$2" before path base code
  before=$(wc -l < "$SVC"); resp=$(post "{\"name\":\"self.screen.snapshot\",\"arguments\":{\"url\":\"$UPURL\",\"quality\":90}}")
  log "snapshot[$label] sent=$(echo "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sent"))' 2>/dev/null)"
  path=""; for i in $(seq 1 80); do path=$(tail -n +$((before+1)) "$SVC" | grep -o '\[debug\] upload [0-9]* bytes -> [^ ]*snapshot-[^ ]*\.jpg' | tail -1 | sed 's/.*-> //'); [ -n "$path" ] && break; sleep 0.5; done
  if [ -z "$path" ]; then log "ABORT no upload for $label"; return 3; fi
  base=$(basename "$path"); log "UPLOAD[$label] $path"
  code=$(curl -s -m 15 -o "$out" -w '%{http_code}' -H "Authorization: Bearer $TOK" "$BASE/debug/photo/$base")
  log "FETCH[$label] /debug/photo/$base -> HTTP $code -> $out"
  log "FILE[$label] $(ls -l "$out" | awk '{print $5}') bytes sha256=$(shasum -a 256 "$out" | cut -d' ' -f1)" ; }
ts=$(date '+%Y%m%d-%H%M%S')
log "=== D recapture start $(date '+%F %T %Z') ==="
log "MUTE $(curl -s -m 5 -H "Authorization: Bearer $TOK" "$BASE/debug/mute")"
resp=$(post '{"name":"self.screen.set_view","arguments":{"view":3}}')
log "set_view view=3 sent=$(echo "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("sent"))' 2>/dev/null)"
sleep 2
shot "D1" "$EV/view-D-$ts.jpg"
sleep 3
shot "D2" "$EV/view-D-second-$ts.jpg"
log "SVC-view $(grep -n '\[debug\] mcp self.screen.set_view' "$SVC" | tail -1)"
log "SVC-upload $(grep -n '\[debug\] upload' "$SVC" | tail -1)"
log "=== D recapture done $(date '+%F %T %Z') ==="
