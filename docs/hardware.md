# Hardware decisions

Checked 2026-10-21 against `78/xiaozhi-esp32` @ main (52 board families, 171 variants).
Pin tables quoted from that repo, not from vendor pages.

## Board in hand: Xingzhi Cube 1.54 (single mic, no AEC)

Confirmed from the user's own port in `~/AI_Workspace/01_Code/projects/esp-claw`:

- `application/edge_agent/boards/community/xingzhi_cube_154/` (uncommitted port)
- custom emote assets at `components/common/emote/assets_local/emoji_large/`
  (`swim.eaf`, `offline.eaf`, 1.2 MB each, 284x240, 20 fps, loop)
- Official xiaozhi board: `nologo/xingzhi-cube-1.54tft-wifi`, pins match one for one:

```
MIC  WS=4  SCK=5  DIN=6
SPK  DOUT=7 BCLK=15 LRCK=16
LCD  DC=8  CS=14  RST=18  BL=13
KEY  BOOT=0 VOL+=40 VOL-=39
```

Hardware facts that change the product:

- ESP32-S3-WROOM-1-N16R8, ST7789 240x240, no touch
- **No ES8311 / ES7210.** Audio is direct I2S to an NS4150B PA (GPIO21 enable).
  One microphone, no playback reference channel.
- Consequence: no AEC possible on device. Playback must be half-duplex
  (drop mic frames while speaking + tail cooldown). Desk use, 1-2 m only.
- Board is in family use; do not reflash it. Buy a second board instead.

## Chosen (2026-10-21): chd-esp32s3-box-lcd35

Bought the "full" variant: **3.5" capacitive, ST7796, 480x320, with camera**.

Official build name is `chd-esp32s3-box-lcd35`. The panel matches the config
exactly (same size, same driver), so device-side work really is zero lines:

```
CONFIG_USE_DEVICE_AEC=y            # device-side AEC, the whole point
CONFIG_CHD_ESP32S3_BOX_LCD_35=y    # 3.5" 480x320 instead of 2.8" 320x240
```

Camera pins are already defined in the same `config.h` (OV2640/OV5640, DVP
parallel, D0-D7 + XCLK/PCLK/VSYNC), and the board class implements
`InitializeCamera()`.

Power: 3.5" panel + camera needs 5V/2A; do not run it off a laptop USB port.

## Vendor docs cross-check (2026-10-21)

Seller package for the V2.0 board, archived at
`~/AI_Workspace/02_Archive/chd-board-docs-2026-10/` (6 files, no factory bin).

Panel: **E350S030-D** (亦亚徽/Yoyohoo), 3.5", 320x480, RGB565, 4-wire SPI,
driver **ST7796U**, outline 55.26 x 84.52 x 2.70 mm.

Pin table (V2.0) matches the official `config.h` exactly:

```
LCD  DC=4  CS=5  SDA=6  SCK=7
I2S  MCLK=2  LRCLK=45  SCLK=17  ADC_SDOUT=16  CODEC_DSDIN=15
```

Gotchas from the vendor README:

- Camera, expansion IO and the TF card **share pins**. Remove the camera or the
  SD card when running the other. We do not use SD, so the camera can stay.
- Camera orientation is a runtime fix, not a wiring issue:
  `s->set_hmirror(s, 1); s->set_vflip(s, 0);`
- The board is derived from Espressif ESP32-S3-BOX-3; the vendor tutorial tells
  you to disable OTA or the device may pull the Espressif box3 firmware. The
  upstream `chd-esp32s3-box` build already has its own OTA identity, so this
  only matters if flashing the vendor's older firmware.
- No factory firmware in the package: roll back with a full 16 MB dump taken
  before the first flash.

## Candidates considered

Only boards with `AUDIO_INPUT_REFERENCE true` qualify - that flag is what
makes barge-in possible at all.

| Board | Screen | Audio | Config | Note |
|---|---|---|---|---|
| `chd/chd-esp32s3-box` | 2.8" 320x240 ST7789 | ES8311 + ES7210 dual mic, AEC ref | ready | **bought the 3.5" variant**, see above |
| `nologo/xingzhi-metal-1.54-wifi` | 1.54" 240x240, CST816 touch | ES8311, AEC ref, PCA9557 | ready | same vendor as current board, aluminium shell |
| `espressif/esp32-s3-box-3` | 2.4" 320x240 touch | ES7210 dual mic, AEC ref | ready | best supported, most expensive, fewer CN channels |

48 boards in the tree declare an AEC reference. Screen size is a nice-to-have;
the reference channel is the feature that decides whether interrupts work.

## Rejected: Tuya VWXR2-ES

- SoC is **XR872AT** (ARM Cortex-M4F, 416 KB SRAM + 4 MB PSRAM), not ESP32.
- Firmware is compiled by the Tuya cloud for the "AI voice IR remote" product;
  there is no socket to put our own pipeline behind.
- Cannot run `xiaozhi-esp32` (ESP32-only) and cannot be reflashed with
  ESPHome/Tasmota (those target ESP chips).
- Home Assistant: the official Tuya integration does not expose IR remotes.
  Only cloud API integrations (`EnzoD86/tuya-smart-ir-ac`) or
  `ClusterM/localtuya_rc` work, both requiring a Tuya IoT cloud project and
  IR Control Hub service.
- Kept as a standalone Tuya voice remote. Out of scope for this project.

## Flashing risk

ESP32-S3's ROM bootloader cannot be destroyed by a bad flash; only eFuse
(secure boot / flash encryption) is one-way, and production boards normally
leave it off. Back up the whole 16 MB before flashing:

```
esptool.py --port /dev/cu.usbmodem* read_flash 0 0x1000000 board-original.bin
```

Restore with `write_flash 0 board-original.bin`.

## Toolchain

`78/xiaozhi-esp32` requires **ESP-IDF >= 6.0.1** (6.1 recommended); 5.x is
unsupported. This Mac currently has 5.5.4 at `~/AI_Workspace/05_Tools/esp-idf-5.5.4`.
