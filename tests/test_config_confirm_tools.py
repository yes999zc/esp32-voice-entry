"""Drift guard for `config.yaml safety.confirm_tools`.

The gate compares firmware tool names by exact string, so a typo in the config
silently disables the spoken confirmation on BOTH `/debug/tool` (session.py) and
`/debug/mcp` (vision.py). That is what happened before the 2.5.3 audit: three of
four entries were spelled `self.system.*` and never matched.

The whitelist below is the firmware's own registry, read by hand from the local
checkout (`05_Tools/xiaozhi-esp32`, PROJECT_VER 2.5.3). Each entry cites the file
and line it comes from; update both sides together, never the config alone.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CONFIG_PATH = ROOT / "config.yaml"

# Firmware source: 05_Tools/xiaozhi-esp32 @ PROJECT_VER 2.5.3
FIRMWARE_CONFIRM_TOOLS = {
    # main/mcp_server.cc:132  AddUserOnlyTool("self.reboot", ...)
    "self.reboot": "main/mcp_server.cc:132",
    # main/mcp_server.cc:146  AddUserOnlyTool("self.upgrade_firmware", ...)
    "self.upgrade_firmware": "main/mcp_server.cc:146",
    # main/mcp_server.cc:319  AddUserOnlyTool("self.assets.set_download_url", ...)
    "self.assets.set_download_url": "main/mcp_server.cc:319",
    # main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc:757
    #   AddTool("self.system.reconfigure_wifi", ...)
    "self.system.reconfigure_wifi":
        "main/boards/chd/chd-esp32s3-box/chd_esp32s3_box_board.cc:757",
}

# Spellings shipped before the audit. The firmware has no such tools, so keeping
# them would be dead config that only looks like protection.
LEGACY_WRONG_NAMES = [
    "self.system.reboot",
    "self.system.upgrade_firmware",
    "self.system.set_download_url",
]


def confirm_tools() -> list:
    with open(CONFIG_PATH) as fh:
        cfg = yaml.safe_load(fh)
    return cfg["safety"]["confirm_tools"]


def test_confirm_tools_are_exactly_the_firmware_four():
    names = confirm_tools()
    assert isinstance(names, list) and all(isinstance(n, str) for n in names)
    assert len(names) == len(set(names)) == 4, names
    assert set(names) == set(FIRMWARE_CONFIRM_TOOLS), (
        "config.yaml safety.confirm_tools drifted from the firmware registry: "
        f"config={sorted(set(names))} firmware={sorted(FIRMWARE_CONFIRM_TOOLS)}")


def test_every_entry_names_a_real_firmware_tool():
    """Per-entry check so the failure message points at the offending line."""
    for name in confirm_tools():
        assert name in FIRMWARE_CONFIRM_TOOLS, (
            f"{name!r} is not a firmware tool name; "
            f"known: {sorted(FIRMWARE_CONFIRM_TOOLS)}")


def test_every_entry_is_a_raw_firmware_name():
    """Raw names only: the config is compared after alias normalization."""
    for name in confirm_tools():
        assert name.startswith("self."), f"{name!r} looks like a speech alias"


def test_legacy_wrong_names_are_not_in_the_list():
    present = set(confirm_tools())
    for name in LEGACY_WRONG_NAMES:
        assert name not in present, (
            f"legacy non-existent name {name!r} is back in safety.confirm_tools")
