from pathlib import Path

import pytest

from scripts.pair_firmware import pair


def test_pairing_keeps_one_secret_and_rejects_invalid_input(tmp_path: Path):
    sdkconfig = tmp_path / "sdkconfig"
    token_file = tmp_path / "device.token"
    sdkconfig.write_text('CONFIG_OTA_URL="http://example.invalid/ota"\n')
    token_file.write_text("short\n")
    with pytest.raises(ValueError):
        pair(sdkconfig, token_file)
    assert "XIAOZHI_DEVICE_TOKEN" not in sdkconfig.read_text()

    token_file.write_text("a" * 43 + "\n")
    pair(sdkconfig, token_file)
    pair(sdkconfig, token_file)
    assert sdkconfig.read_text().count("CONFIG_XIAOZHI_DEVICE_TOKEN=") == 1
    assert (sdkconfig.stat().st_mode & 0o777) == 0o600
