# Font Audit — Device UI and Admin Console

Date: 2026-10-29. Scope: firmware Phase B UI (480x320) and `/admin` page. Read-only audit.

## Device UI

| Item | Current | Finding |
|---|---|---|
| Primary text | `font_noto_sans_common_20_4`, 20 px | Good CJK/Latin coverage; line spacing 33/31/27 px is readable. |
| Small text | `lv_font_montserrat_14` | Latin-only. Used for telemetry (`status_line_`), numeric values and the Chinese A-view metric titles before `ApplyPhaseBFonts()` re-points them to Noto. Risk: a theme/font init failure leaves 状态/内存/帧 as tofu. |
| B cards | 20 px, 152x62 cells | Titles and values fit (`音频帧`, `A324 D18`); values use dot truncation at 140 px. |
| A metrics | 20 px values, 14 px labels | Values aligned center; `帧` count forced to a single clipped line. |
| Hierarchy | size + muted color only | No weight axis in the embedded font; hierarchy is acceptable but flat. |

Recommendation:
1. Use Noto/active CJK font for every label that can contain Chinese; keep Montserrat only for ASCII telemetry. This removes the current init-order dependency.
2. Keep 20 px for primary and 14 px for secondary; do not go below 14 px on the 480x320 panel.

## Admin console

| Item | Current | Finding |
|---|---|---|
| Body | 15 px/1.55 system sans (`-apple-system`, Segoe UI, PingFang SC, Microsoft YaHei) | Platform-appropriate CJK; good readability. |
| Headings/stats | `ui-serif, Georgia, "Songti SC", Times` | Intentional paper look on macOS; Windows/Linux may fall back to a different serif, so the visual identity is not deterministic. |
| Small labels | brand 11 px, hints 12–12.5 px | 11 px is below a comfortable desktop minimum; hints are borderline. |
| Numeric values | serif, no tabular setting | Numbers can jitter when live values update. |
| 480 px | stat value 19 px; base 15 px | No overflow in the 480 px screenshots. |

Recommendation:
1. Add `"Noto Serif CJK SC", "Source Han Serif SC"` before Georgia, or switch headings to the same sans stack as body for cross-platform consistency.
2. Raise the 11 px brand label to 12 px; keep hints >= 12 px.
3. Add `font-variant-numeric: tabular-nums` to stat values and live telemetry.

## Cross-surface note

The device uses Noto Sans while the admin uses serif headings. That contrast is deliberate (paper/ink console), but it means the two surfaces do not share a typographic voice. Decide whether the console should mirror the device's sans stack or keep the editorial serif.

## Applied 2026-10-29

- Admin now uses one UI sans stack for headings, stats and controls; serif fallbacks removed.
- `.primary` / `.ghost` share one 34 px, 8 px-radius button geometry; mute card uses the same buttons as volume/screenshot/turn.
- Mobile header uses a two-row grid so brand/status/actions never clip at 480 px; `[hidden]` is enforced.


- Device: `a_metric_titles_` now starts on the active CJK font; Montserrat is only used for ASCII telemetry/numbers.
- Admin: serif stack adds Noto Serif CJK SC / Source Han Serif SC; brand label 11→12 px; stat values use `tabular-nums`.
- Firmware app flashed at 0x20000 (NVS preserved), app md5 `189d13e64658738bb0ba9fa12426e478`.

## Evidence

- Device: B-view snapshot `20261029-113658.jpg`; A-view cards/telemetry snapshots.
- Admin: 480 px overview/control screenshots; live CDP checks found no horizontal overflow.
