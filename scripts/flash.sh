#!/bin/bash
# Flash the CHD board. Board must be in download mode:
#   power off -> hold BOOT -> power on (only if no /dev/cu.usbmodem* appears)
#
# Usage: ./scripts/flash.sh /dev/cu.usbmodem1234 [--no-backup]
set -euo pipefail

PORT="${1:?usage: flash.sh <serial-port> [--no-backup]}"
NO_BACKUP="${2:-}"
FW="$HOME/AI_Workspace/05_Tools/xiaozhi-esp32/build/merged-binary.bin"
ESPEED="$HOME/.espressif/python_env/idf6.1_py3.12_env/bin/python"
ESPTOOL=(-m esptool --chip esp32s3 -p "$PORT" -b 460800)

[[ -f "$FW" ]] || { echo "missing firmware: $FW"; exit 1; }

if [[ "$NO_BACKUP" != "--no-backup" ]]; then
  OUT="$HOME/AI_Workspace/02_Archive/esp32-voice-firmware/factory-$(date +%Y%m%d-%H%M).bin"
  mkdir -p "$(dirname "$OUT")"
  echo "== dumping 16 MB factory flash -> $OUT"
  "$ESPEED" "${ESPTOOL[@]}" read-flash 0 0x1000000 "$OUT"
  ls -lh "$OUT"
fi

echo "== writing $FW"
"$ESPEED" "${ESPTOOL[@]}" --before default-reset --after hard-reset write-flash 0x0 "$FW"
echo "== done. device reboots into our OTA endpoint; watch logs with:"
echo "   idf.py -p $PORT monitor"
