#!/usr/bin/env python3
"""Run the interactive power calibration for the current test station."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "saved_data"
DEFAULT_CALIBRATION_DIRECTORY = DEFAULT_OUTPUT_DIRECTORY / "calibration"

# Preserve direct-file execution in addition to ``python -m`` execution.
if __package__ in (None, ""):
    sys.path.insert(0, str(REPOSITORY_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calibrate the current station's voltage and current sensors."
    )
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=DEFAULT_CALIBRATION_DIRECTORY,
        help="directory containing WH-station<number>.json files",
    )
    return parser


def _measurement_text(value: object, precision: int, suffix: str = "") -> str:
    if value is None:
        return "None"
    return f"{float(value):.{precision}f}{suffix}"


def monitor_power(
    bus: object,
    calibration: dict[str, object],
    duration_seconds: float,
    *,
    read_measurement: Callable[[object, dict[str, object]], dict | None],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Display calibrated power readings once per second for the requested time."""
    start = monotonic()
    while monotonic() - start < duration_seconds:
        timestamp = datetime.now().isoformat(timespec="seconds")
        measurement = read_measurement(bus, calibration)
        if measurement is None:
            print(f"{timestamp}  I2C READ ERROR", flush=True)
            sleep(1.0)
            continue

        print(
            f"{timestamp}  "
            f"Vrms={_measurement_text(measurement['voltage_rms'], 1)}  "
            f"Irms={_measurement_text(measurement['current_rms'], 2)}  "
            f"P={_measurement_text(measurement['real_power'], 1, ' W')}  "
            f"Q={_measurement_text(measurement['reactive_power'], 1, ' VAR')}  "
            f"S={_measurement_text(measurement['apparent_power'], 1, ' VA')}  "
            f"PF={_measurement_text(measurement['power_factor'], 3)}  "
            f"(raw vr={measurement['voltage_rms_raw']} "
            f"ir={measurement['current_rms_raw']})",
            flush=True,
        )
        sleep(1.0)


def prompt_monitor_duration_seconds() -> int:
    """Prompt for a finite post-calibration monitoring duration."""
    try:
        hours = int(input("Monitor for how many hours? ").strip())
        minutes = int(input("Monitor for how many minutes? ").strip())
    except ValueError:
        print("Invalid input. Using a five-minute monitoring period.")
        return 5 * 60
    if hours < 0 or minutes < 0 or (hours == 0 and minutes == 0):
        print("Duration must be positive. Using a five-minute monitoring period.")
        return 5 * 60
    return (hours * 60 + minutes) * 60


def run(calibration_directory: Path) -> int:
    """Open the power sensor and perform the existing guided calibration."""
    # Hardware imports stay deferred so --help and module imports work off-station.
    from smbus2 import SMBus

    from software.helpers.hardware_map import I2C_BUS
    from software.helpers.helper_power_functions import (
        calibrate,
        get_calibration_from_JSON,
        read_measurement_values,
    )

    resolved_directory = calibration_directory.resolve()
    resolved_directory.mkdir(parents=True, exist_ok=True)
    output_directory = resolved_directory.parent
    calibration = get_calibration_from_JSON(
        str(resolved_directory),
        str(output_directory),
    )

    print("Starting full power calibration.")
    print(f"Calibration directory: {resolved_directory}")
    with SMBus(I2C_BUS) as bus:
        calibrate(
            bus,
            calibration,
            str(resolved_directory),
            str(output_directory),
        )
        calibration = get_calibration_from_JSON(
            str(resolved_directory),
            str(output_directory),
        )
        duration_seconds = prompt_monitor_duration_seconds()
        print("Monitoring calibrated power. Press Ctrl+C to stop early.")
        try:
            monitor_power(
                bus,
                calibration,
                duration_seconds,
                read_measurement=read_measurement_values,
            )
        except KeyboardInterrupt:
            print("\nPower monitoring stopped by user.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args.calibration_dir)


if __name__ == "__main__":
    raise SystemExit(main())
