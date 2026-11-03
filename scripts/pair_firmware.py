#!/usr/bin/env python3
"""Put the server's private device token into an ESP-IDF sdkconfig.

Run after the firmware's build.py has generated sdkconfig and before idf.py
build. The token is read from disk and never printed or passed on a command line.
"""
import argparse
import re
from pathlib import Path

KEY = "CONFIG_XIAOZHI_DEVICE_TOKEN="


def pair(sdkconfig: Path, token_file: Path) -> None:
    if not sdkconfig.is_file():
        raise ValueError(f"missing sdkconfig: {sdkconfig}")
    token = token_file.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
        raise ValueError("device token is missing or has an invalid format")
    lines = [line for line in sdkconfig.read_text(encoding="utf-8").splitlines()
             if not line.startswith(KEY)]
    lines.append(f'{KEY}"{token}"')
    sdkconfig.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sdkconfig.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path, help="xiaozhi-esp32 repository path")
    parser.add_argument("--token-file", type=Path,
                        default=Path("~/.esp32-voice/device.token"))
    args = parser.parse_args()
    pair(args.firmware.expanduser() / "sdkconfig", args.token_file.expanduser())
    print("Firmware sdkconfig paired. Run idf.py build, then flash app at 0x20000.")


if __name__ == "__main__":
    main()
