#!/usr/bin/env python3
"""Build a 16 KB NVS partition image that stores ``wifi/ota_url`` on the device.

Why this script lives in *this* (server) repo
---------------------------------------------
The blob it produces contains one thing: the URL of *your* OTA server, i.e. this
repo's ``/xiaozhi/ota/`` endpoint. The flashing recipe and the provisioning notes
that make sense of it are also here (``docs/quickstart-single-board.md``,
``docs/firmware-release.md``). The firmware repo stays vendor-shaped, and nothing
in it needs to know which LAN address your server happens to have today.

What the device does with it
----------------------------
``main/ota.cc`` reads NVS ``wifi/ota_url`` first and only falls back to the
compiled-in ``CONFIG_OTA_URL`` when the key is absent, so a pre-baked NVS lets a
stock (placeholder-URL) factory image talk to your server without a rebuild.
The stored value is used **verbatim as the complete URL**: nothing is concatenated
onto it, and this server only serves ``/xiaozhi/ota/`` (``src/ota.py``), so a bare
base such as ``http://host:4411`` would 404. Therefore this script *normalizes*
the input: a base (no path, or just ``/``) becomes ``<base>/xiaozhi/ota/``;
an explicit path (e.g. your own reverse-proxy route) is kept as given.
The provisioning web UI can write the same key: ``/advanced/submit`` on the
SoftAP page (``78__esp-wifi-connect/wifi_configuration_ap.cc:599-610`` opens NVS
namespace ``wifi`` and calls ``nvs_set_str("ota_url", ...)``).

Usage
-----
    python3 scripts/make_nvs_ota.py --url http://<server-ip>:4411
    python3 scripts/make_nvs_ota.py --url http://<server-ip>:4411/xiaozhi/ota/   # same bytes
    python3 scripts/make_nvs_ota.py --url https://voice.example.com --out /tmp/nvs-ota.bin

    # then, with the board in download mode:
    esptool.py --chip esp32s3 -p <serial-port> write-flash 0x9000 /tmp/nvs-ota.bin

WARNING: flashing 0x9000 replaces the whole NVS partition, so the device loses
its saved Wi-Fi credentials (and any other NVS state) and has to be re-provisioned
through the SoftAP page. That is exactly why this is an *alternative* to
rebuilding the firmware with ``XIAOZHI_OTA_BASE``, not a no-op.

Requires ESP-IDF (``IDF_PATH`` set, e.g. after ``source <esp-idf>/export.sh``)
because the CSV is compiled by ESP-IDF's own
``nvs_flash/nvs_partition_generator/nvs_partition_gen.py``.

Exit codes: 0 = success, 1 = generation failure, 2 = usage/environment error.
"""
import argparse
import csv
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_SIZE = 0x4000  # partitions/v2/16m.csv: nvs,data,nvs,0x9000,0x4000
NVS_FLASH_OFFSET = "0x9000"
NAMESPACE = "wifi"
KEY = "ota_url"
GEN_RELATIVE = "components/nvs_flash/nvs_partition_generator/nvs_partition_gen.py"
DEFAULT_ENDPOINT_PATH = "/xiaozhi/ota/"  # the only OTA route the server registers (src/ota.py)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Generate an NVS partition image containing wifi/ota_url so a device "
            "with a placeholder OTA URL can be pointed at your own server."
        ),
        epilog=(
            "Flash the result to 0x9000 (the 'nvs' partition of "
            "partitions/v2/16m.csv, 0x4000 bytes). "
            "WARNING: this overwrites the whole NVS partition, so existing Wi-Fi "
            "credentials and other NVS state are lost and the board must go "
            "through SoftAP provisioning again (SSID Xiaozhi-XXXX, "
            "http://192.168.4.1/). Size must be a multiple of 0x1000 and match "
            "the partition size (default 0x4000 = 16 KB). "
            "The firmware uses the stored value as the COMPLETE URL (nothing is "
            "concatenated), so a bare base is completed to <base>/xiaozhi/ota/ here; "
            "pass an explicit path only if your deployment really serves it there."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url",
        required=True,
        help=(
            "URL of your own OTA server, http(s):// only. The firmware uses it "
            "verbatim, so a bare base (http://<server-ip>:4411) is normalized to "
            "http://<server-ip>:4411/xiaozhi/ota/; a full endpoint is stored as-is"
        ),
    )
    parser.add_argument(
        "--out",
        default="nvs-ota.bin",
        help="Output image path (default: nvs-ota.bin)",
    )
    parser.add_argument(
        "--size",
        default=hex(DEFAULT_SIZE),
        help=f"NVS partition size in bytes, multiple of 0x1000 (default: {hex(DEFAULT_SIZE)})",
    )
    parser.add_argument(
        "--keep-csv",
        metavar="PATH",
        help="Also write the intermediate CSV to PATH (debugging)",
    )
    return parser.parse_args(argv)


def normalize_url(url):
    """Return the exact string to store in NVS ``wifi/ota_url``.

    The firmware treats this value as the complete endpoint (``main/ota.cc``
    ``GetCheckVersionUrl`` returns the NVS string verbatim, no path is concatenated)
    and the server only answers ``/xiaozhi/ota/`` (``src/ota.py``). A bare base
    would therefore 404, so a base with an empty path (or ``/``) is completed to
    ``<base>/xiaozhi/ota/``. Any other explicit path is kept exactly as given, so
    a custom deployment route still works.
    """
    raw = url.strip()
    lowered = raw.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError(f"--url must start with http:// or https:// (got {url!r})")
    if any(ch in raw for ch in ',"\n\r\t '):
        raise ValueError(
            f"--url must not contain spaces, quotes, commas or newlines (got {url!r})"
        )

    parts = urlsplit(raw)
    if not parts.netloc:
        raise ValueError(f"--url has no host (got {url!r})")
    if parts.query or parts.fragment:
        raise ValueError(
            f"--url must not carry a query string or fragment (got {url!r})"
        )

    path = parts.path
    if path in ("", "/"):
        path = DEFAULT_ENDPOINT_PATH
    elif path == DEFAULT_ENDPOINT_PATH.rstrip("/"):
        # The server registers the route with a trailing slash, so the
        # slash-less spelling of the default endpoint would 404. Accept it and
        # store the canonical form rather than passing a broken URL to the device.
        path = DEFAULT_ENDPOINT_PATH
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def parse_size(text):
    try:
        size = int(text, 0)
    except ValueError:
        raise ValueError(f"--size must be an integer (decimal or 0x-prefixed), got {text!r}")
    if size <= 0:
        raise ValueError("--size must be positive")
    if size % 0x1000:
        raise ValueError(f"--size must be a multiple of 0x1000, got {hex(size)}")
    return size


def find_generator():
    idf_path = os.environ.get("IDF_PATH", "").strip()
    if not idf_path:
        raise RuntimeError(
            "IDF_PATH is not set. Source ESP-IDF first, e.g.\n"
            "    source ~/AI_Workspace/05_Tools/esp-idf-6.1/export.sh\n"
            "then re-run this script."
        )
    gen = Path(idf_path) / GEN_RELATIVE
    if not gen.is_file():
        raise RuntimeError(
            f"nvs_partition_gen.py not found at {gen} -- IDF_PATH ({idf_path}) "
            "does not look like an ESP-IDF checkout"
        )
    return gen


def write_csv(path, url):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["key", "type", "encoding", "value"])
        writer.writerow([NAMESPACE, "namespace", "", ""])
        writer.writerow([KEY, "data", "string", url])


def main(argv=None):
    args = parse_args(argv)
    try:
        url = normalize_url(args.url)
        size = parse_size(args.size)
        generator = find_generator()
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nvs-ota-") as tmpdir:
        csv_path = Path(tmpdir) / "ota_url.csv"
        write_csv(csv_path, url)
        if args.keep_csv:
            keep = Path(args.keep_csv).expanduser()
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

        cmd = [sys.executable, str(generator), "generate", str(csv_path), str(out_path), str(size)]
        print("+ " + " ".join(cmd[:-2] + [str(out_path), str(size)]))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            print(f"error: nvs_partition_gen.py failed (exit {result.returncode})", file=sys.stderr)
            return 1

    blob = out_path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    print(f"namespace: {NAMESPACE}  key: {KEY}")
    print(f"input: {args.url}")
    print(f"stored value (NVS wifi/{KEY}): {url}")
    print(f"image: {out_path}  {len(blob)} bytes  sha256 {digest}")
    print(
        f"flash: esptool.py --chip esp32s3 -p <serial-port> write-flash "
        f"{NVS_FLASH_OFFSET} {out_path}   # wipes NVS -> re-provision via SoftAP"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
