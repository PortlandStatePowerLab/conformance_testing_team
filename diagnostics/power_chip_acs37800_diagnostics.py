from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from smbus2 import SMBus

# -----------------------------
# Helpers
# -----------------------------
from diagnostics.helpers_diagnostics.helper_power_diagnostics import (
    read_configuration,
    print_configuration_summary,
    read_live_snapshot,
    print_live_snapshot,
    read_instantaneous_burst,
    print_instantaneous_burst,
    parse_args,
)

from helpers.hardware_map import (
        I2C_BUS,
        ACS37800_I2C_ADDR,
)

def main() -> int:
    args = parse_args()
    if args.samples < 1 or args.burst_samples < 0 or args.interval < 0 or args.burst_delay < 0:
        print("Invalid sample count or delay.", file=sys.stderr)
        return 2

    hostname = socket.gethostname()
    started = datetime.now()
    args.output_folder.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "diagnostic_program": "acs37800_power_chip_diagnostic.py",
        "read_only": True,
        "hostname": hostname,
        "started_at": started.isoformat(timespec="seconds"),
        "i2c_bus": I2C_BUS,
        "i2c_device_path": f"/dev/i2c-{I2C_BUS}",
        "acs37800_i2c_address_hex": f"0x{ACS37800_I2C_ADDR:02X}",
        "settings": {
            "live_snapshot_count": args.samples,
            "live_snapshot_interval_seconds": args.interval,
            "instantaneous_burst_count": args.burst_samples,
            "instantaneous_burst_delay_seconds": args.burst_delay,
        },
    }

    print("ACS37800 power-chip diagnostic")
    print(f"Host: {hostname}")
    print(f"I2C: /dev/i2c-{I2C_BUS}, address 0x{ACS37800_I2C_ADDR:02X}")
    print("Mode: READ ONLY")

    try:
        with SMBus(I2C_BUS) as bus:
            configuration = read_configuration(bus)
            report["configuration"] = configuration
            print_configuration_summary(configuration)

            live_samples = []
            for index in range(args.samples):
                snapshot = read_live_snapshot(bus)
                live_samples.append(snapshot)
                print_live_snapshot(snapshot)
                if index < args.samples - 1 and args.interval > 0:
                    time.sleep(args.interval)
            report["live_samples"] = live_samples

            if args.burst_samples > 0:
                print(f"\nCollecting {args.burst_samples} instantaneous VCODES/ICODES/PINSTANT samples...")
                report["instantaneous_burst"] = read_instantaneous_burst(bus, args.burst_samples, args.burst_delay)
            else:
                report["instantaneous_burst"] = []

    except (OSError, PermissionError) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print(f"\nI2C ERROR: {exc}", file=sys.stderr)
        print("Check I2C enablement, /dev/i2c-1, chip power, and address 0x60.", file=sys.stderr)

    finished = datetime.now()
    report["finished_at"] = finished.isoformat(timespec="seconds")
    report["duration_seconds"] = (finished - started).total_seconds()
    filename = f"acs37800_diagnostic_{hostname}_{started.strftime('%Y-%m-%d_%H%M%S')}.json"
    output_path = args.output_folder / filename
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(report, output_file, indent=2)
        output_file.write("\n")
    print(f"\nSaved diagnostic report to: {output_path}")
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())