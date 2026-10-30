# scripts/fonts — UI v2 字体子集

字体二进制**不入 git**（`build/`、`fonts-src/` 已被本目录 `.gitignore` 忽略）。

| 文件 | 作用 |
|---|---|
| `make_charset.py` | 生成 4 个字符集：800 字（正文）、500 字（明细）、36 字（标题/房间名）、ASCII+符号（等宽） |
| `build_fonts.sh` | `lv_font_conv@1.5.3` 生成 6 个 bpp=4 `.bin`，并校验总体积 ≤250 KiB |
| `render_ui_v2.py` | 用占位字体渲染 `docs/face/ui-v2/*.png`（不参与固件） |

## 用法

```sh
# 1) 放字体源文件（需自行从官方渠道下载，见 docs/fonts/LICENSE-notes.md）
mkdir -p scripts/fonts/fonts-src
cp ~/Downloads/MiSans-Regular.ttf      scripts/fonts/fonts-src/
cp ~/Downloads/JetBrainsMono-Regular.ttf scripts/fonts/fonts-src/

# 2) 生成字符集 + 字体
FONT_DIR=scripts/fonts/fonts-src ./scripts/fonts/build_fonts.sh

# 3) 产物在 scripts/fonts/build/fonts/*.bin（不进 git），拷进固件 assets 后由
#    lv_binfont_create_from_buffer() 加载，见 docs/fonts/font-spec.md
```

依赖：Node.js（npx）、Python 3.9+。链路上固定 `lv_font_conv@1.5.3`，与固件仓
`78__xiaozhi-fonts` 使用的版本一致（该仓另有一个 CBIN 用 fork，本目录不用）。
