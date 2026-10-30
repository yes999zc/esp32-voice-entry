# B2 静音真机证据（2026-10-28 17:45–17:49）

- 固件：`9f99d88`（B2），刷机后板上 app md5 `d68b6db8fd2bb0e1b8ef0a7bc54b97d1`；之后第二次刷 C1 `b7d1d7c`（md5 `51b4f24f…`），B2 功能不变。
- 屏幕：`docs/face/b2-muted-20261028.jpg`（MCP `self.screen.snapshot` 实拍）——灰化遮罩 +「已静音 / 点左侧按钮解除」+ 左侧按钮「解除静音」。
- 按钮：串口 `mute ui total=100 ms (local render=5 ms, network+wait=95 ms)`；`server-confirmed muted` 后 `Mute hold ON`；再点解除 `hold OFF`。
- 端侧 0 上行（30 s）：`tx_audio=0 capture=0 codec_in=0` ×4；服务端 `frames_in=0 dropped=0 accepted=0 turns=0` 前后不变（B1 口径 A 对照为 653/1889 持续增长）。
- 断电/重启保持：静音态下硬复位（esptool hard reset）→ 启动 `Mute: sync ok: muted=1 via GET`、`Mute hold ON`、`mute ui state=3 last_confirmed=1`；随后 `mute: tx_audio=0 capture=0 codec_in=0 (10s)`。
- 解除后唤醒：CLI `off` → `server-confirmed unmuted, wake word restored`；1.3 s 后「你好小智」被检出（`Wake word detected`）。
- 说明：复位用 esptool hard reset 代替拔电；屏幕「已静音」由 snapshot 实拍，不是用户目视记录。B2 的 3 条现场项已由上述证据覆盖。
