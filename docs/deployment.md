# 部署指南 / Deployment guide

## 中文

1. 准备 Python 3.13、设备、2.4 GHz Wi-Fi，以及一台与设备处于同一网络的电脑。下载本仓库和[固件仓库](https://github.com/yes999zc/xiaozhi-esp32)。
2. 在本仓库创建虚拟环境并安装依赖：

   ```sh
   python3.13 -m venv .venv313
   .venv313/bin/pip install -r requirements.txt
   cp config.example.yaml config.local.yaml
   ```

3. 编辑 `config.local.yaml`：把 `server.ws_url` 和 `server.vision_url` 中的占位地址改成服务电脑的局域网地址；选择 LLM 和 TTS 提供商，准备配置里指定的 ASR、VAD、TTS 模型文件并设置所需 API 密钥。配置项及说明见 `config.example.yaml`。即使用云端 TTS，也要准备 Matcha 后备模型与 vocoder。模型下载示例见 [单板指南的模型章节](quickstart-single-board.md)（其历史发布版本信息请以固件仓库为准）。密钥不要提交到 Git。
4. 启动服务：

   ```sh
   cd src
   ../.venv313/bin/python server.py --config ../config.local.yaml
   ```

   首次启动生成 `~/.esp32-voice/control.token` 和 `~/.esp32-voice/device.token`。前者用于控制台，后者用于设备配对，请保密。
5. 为匹配的板型安装[固件发布包](https://github.com/yes999zc/xiaozhi-esp32/releases)，配置 Wi-Fi、OTA 地址与设备令牌。公开镜像内的 OTA 地址是占位值，不能直接连接你的服务。对于已有固件的同款设备，可以使用 `scripts/make_nvs_ota.py --help` 生成包含 OTA 地址和设备令牌的 NVS 镜像；写入 NVS 会清除已有 Wi-Fi 配置，请先备份。此工具需要先安装并加载 ESP-IDF。首次安装和其他板型请参照固件仓库说明。下面的命令针对该固件的 16 MB 分区布局，先替换尖括号内容：

   ```sh
   source <esp-idf>/export.sh
   python3 scripts/make_nvs_ota.py --url http://<服务电脑地址>:4411 --device-token-file ~/.esp32-voice/device.token --out /tmp/esp32-nvs.bin
   python -m esptool --chip esp32s3 -p <串口> write-flash 0x9000 /tmp/esp32-nvs.bin
   ```

   文件包含私有令牌，请勿分享或提交。写入后按设备配网提示重新连接 Wi-Fi。
6. 打开 `http://<服务电脑地址>:4411/admin`，输入 `~/.esp32-voice/control.token` 的内容。设备上线后，在控制台查看状态；远程唤醒前先解除静音。

## English

1. Prepare Python 3.13, a device, 2.4 GHz Wi-Fi and a computer on the same network. Download this repository and the [firmware repository](https://github.com/yes999zc/xiaozhi-esp32).
2. Create the environment and local configuration using the commands in step 2 above.
3. Edit `config.local.yaml`: set `server.ws_url` and `server.vision_url` to the service computer's LAN address; select LLM and TTS providers, supply the configured ASR, VAD and TTS models, and set any required API keys. See `config.example.yaml` for options. The Matcha fallback model and vocoder are required even with cloud TTS. Model download examples are in the [single-board guide](quickstart-single-board.md); use the firmware repository for current release information. Keep secrets out of Git.
4. Start the service with the commands in step 4 above. The first start creates `~/.esp32-voice/control.token` for the console and `~/.esp32-voice/device.token` for pairing. Keep both private.
5. Install a matching [firmware release](https://github.com/yes999zc/xiaozhi-esp32/releases), then configure Wi-Fi, your OTA address and the device token. The public image contains a placeholder OTA address. For a compatible existing device, `scripts/make_nvs_ota.py --help` describes generating an NVS image with your OTA address and device token. Writing NVS clears saved Wi-Fi settings; back up first. This tool requires ESP-IDF to be installed and loaded. For the 16 MB partition layout, use the commands in step 5 above after replacing the placeholders with your ESP-IDF path, server address and serial port. The generated image contains a private token; do not share or commit it. Reconfigure Wi-Fi after writing. See the firmware repository for first-time installation and other boards.
6. Open `http://<server-address>:4411/admin` and enter the contents of `~/.esp32-voice/control.token`. Check the device status and unmute before remote wake.
