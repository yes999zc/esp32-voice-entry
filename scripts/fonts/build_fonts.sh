#!/usr/bin/env bash
# Build the UI v2 bitmap fonts with lv_font_conv (bpp=4), then check the total size.
#
# Fonts are NOT in git. Put the source TTFs here (or point FONT_DIR elsewhere):
#   $FONT_DIR/MiSans-Regular.ttf        MiSans VF/Regular, Xiaomi (free commercial, attribution required)
#   $FONT_DIR/JetBrainsMono-Regular.ttf SIL OFL 1.1 (Copyright 2020 The JetBrains Mono Project Authors)
#
# Usage:  FONT_DIR=~/fonts ./scripts/fonts/build_fonts.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"
OUT="$BUILD/fonts"
FONT_DIR="${FONT_DIR:-$HERE/fonts-src}"
LV_FONT_CONV_VERSION="1.5.3"
LIMIT_KB=250

CJK="$FONT_DIR/MiSans-Regular.ttf"
MONO="$FONT_DIR/JetBrainsMono-Regular.ttf"

[[ -f "$CJK"  ]] || { echo "missing $CJK";  exit 1; }
[[ -f "$MONO" ]] || { echo "missing $MONO"; exit 1; }

python3 "$HERE/make_charset.py"
mkdir -p "$OUT"

conv() { npx --yes "lv_font_conv@$LV_FONT_CONV_VERSION" "$@"; }

# MiSans: CJK + Chinese punctuation. Latin/digits come from the Mono fallback.
conv --font "$CJK" --size 20 --bpp 4 --format bin --no-compress \
     --symbols "$(tr -d '\n' < "$BUILD/charset-800.txt")" \
     -o "$OUT/misans_20_4.bin"
conv --font "$CJK" --size 14 --bpp 4 --format bin --no-compress \
     --symbols "$(tr -d '\n' < "$BUILD/charset-500.txt")" \
     -o "$OUT/misans_14_4.bin"
conv --font "$CJK" --size 32 --bpp 4 --format bin --no-compress \
     --symbols "$(tr -d '\n' < "$BUILD/charset-title.txt")" \
     -o "$OUT/misans_32_4.bin"

# JetBrains Mono: ASCII + a few symbols; 44px is digits/%/° only.
conv --font "$MONO" --size 14 --bpp 4 --format bin --no-compress \
     --symbols "$(tr -d '\n' < "$BUILD/charset-mono.txt")" \
     -o "$OUT/jetbrains_mono_14_4.bin"
conv --font "$MONO" --size 20 --bpp 4 --format bin --no-compress \
     --symbols "$(tr -d '\n' < "$BUILD/charset-mono.txt")" \
     -o "$OUT/jetbrains_mono_20_4.bin"
conv --font "$MONO" --size 44 --bpp 4 --format bin --no-compress \
     --symbols "0123456789.°%/+-" \
     -o "$OUT/jetbrains_mono_44_4.bin"

echo "--- sizes (bytes) ---"
ls -l "$OUT"/*.bin | awk '{printf "%10d  %s\n", $5, $9}'
TOTAL=$(cat "$OUT"/*.bin | wc -c | tr -d ' ')
echo "total: $TOTAL bytes ($((TOTAL / 1024)) KiB, limit ${LIMIT_KB} KiB)"
if (( TOTAL > LIMIT_KB * 1024 )); then
  echo "FAIL: over ${LIMIT_KB} KiB budget" >&2
  exit 2
fi
echo "OK"
