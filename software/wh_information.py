"""Request and decode CTA-2045 water-heater device information."""

from __future__ import annotations

import csv
import os
import subprocess
import tempfile
from pathlib import Path

try:
    from .conformance_test_runner import DEFAULT_CTA_BINARY, DEFAULT_CTA_DIRECTORY
except ImportError:
    from conformance_test_runner import DEFAULT_CTA_BINARY, DEFAULT_CTA_DIRECTORY


CAPABILITY_NAMES = {
    0: "Cycling",
    1: "Tier mode",
    2: "Price mode",
    3: "Temperature Offset",
    4: "Continuously variable power",
    5: "Discretely variable power",
    6: "Advanced Load Up",
    7: "Price Stream",
    8: "SGD Efficiency Level",
}


def decode_capabilities(raw_hex: str) -> list[dict[str, object]]:
    """Return supported, non-reserved capabilities from four protocol bytes."""
    normalized = raw_hex.strip().removeprefix("0x").removeprefix("0X")
    if len(normalized) != 8:
        raise ValueError(f"invalid 32-bit capability bitmap: {raw_hex!r}")
    try:
        bitmap_bytes = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid capability bitmap: {raw_hex!r}") from exc
    return [
        {"bit": bit, "name": name}
        for bit, name in CAPABILITY_NAMES.items()
        if bitmap_bytes[bit // 8] & (1 << (bit % 8))
    ]


def read_wh_information(
    *,
    cta_binary: Path = DEFAULT_CTA_BINARY,
    cta_directory: Path = DEFAULT_CTA_DIRECTORY,
    timeout_seconds: float = 20.0,
) -> dict[str, object]:
    """Run the controller's existing startup query once and return its result."""
    binary = cta_binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(f"CTA controller binary not found: {binary}")

    with tempfile.TemporaryDirectory(prefix="wh_information_") as directory:
        temporary = Path(directory)
        information_path = temporary / "cta_device_information.csv"
        environment = os.environ.copy()
        environment.update(
            {
                "CTA_DEVICE_INFO_LOG_PATH": str(information_path),
                "CTA_EVENT_LOG_PATH": str(temporary / "cta_events.csv"),
                "CTA_COMMODITY_LOG_PATH": str(temporary / "cta_commodity.csv"),
                "CTA_RAW_MESSAGE_LOG_PATH": str(temporary / "cta_raw_messages.csv"),
            }
        )
        try:
            completed = subprocess.run(
                [str(binary)],
                cwd=cta_directory,
                env=environment,
                input="q\n",
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("GetInformation timed out") from exc
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"CTA controller exited with code {completed.returncode}"
                + (f": {details}" if details else "")
            )
        if not information_path.is_file():
            details = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                "water heater did not return device information"
                + (f": {details}" if details else "")
            )
        with information_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 1:
            raise RuntimeError("expected exactly one device-information response")

    row = rows[0]
    if row.get("response_code") != "0":
        raise RuntimeError(
            "GetInformation failed: "
            + (row.get("response_name") or row.get("response_code") or "unknown")
        )
    raw_bitmap = row.get("capability_bitmap_hex", "")
    capabilities = decode_capabilities(raw_bitmap)
    logical_bitmap = int.from_bytes(bytes.fromhex(raw_bitmap), byteorder="little")
    return {
        "timestamp_pacific": row.get("timestamp_pacific", ""),
        "bitmap": f"0x{logical_bitmap:08X}",
        "raw_bitmap": f"0x{raw_bitmap.upper()}",
        "capabilities": capabilities,
    }
