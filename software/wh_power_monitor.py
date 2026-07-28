#!/usr/bin/env python3
"""Change-driven ACS37800 power monitor for conformance tests."""

from __future__ import annotations

import argparse
import csv
import json
import math
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MINIMUM_HEARTBEAT_SECONDS = 60.0
DEFAULT_SAMPLE_INTERVAL_SECONDS = 1.0
DEFAULT_HEARTBEAT_SECONDS = 60.0
DEFAULT_CURRENT_CHANGE_AMPS = 0.015
DEFAULT_POWER_CHANGE_WATTS = 25.0
DEFAULT_VOLTAGE_CHANGE_VOLTS = 1.0
DEFAULT_ON_CURRENT_AMPS = 0.1

CSV_COLUMNS = (
    "timestamp_utc",
    "monitor_elapsed_seconds",
    "status",
    "record_reason",
    "voltage_rms",
    "current_rms",
    "real_power",
    "reactive_power",
    "apparent_power",
    "power_factor",
    "voltage_rms_raw",
    "current_rms_raw",
    "real_power_raw",
    "reactive_power_raw",
    "apparent_power_raw",
)


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def finite_positive(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite number zero or greater")
    return parsed


def heartbeat_interval(value: str) -> float:
    parsed = finite_positive(value)
    if parsed < MINIMUM_HEARTBEAT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be at least {MINIMUM_HEARTBEAT_SECONDS:g} seconds"
        )
    return parsed


def _changed(current: Any, previous: Any, threshold: float) -> bool:
    if current is None or previous is None:
        return current != previous
    return abs(float(current) - float(previous)) >= threshold


def measurement_change_reasons(
    measurement: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    current_change_amps: float,
    power_change_watts: float,
    voltage_change_volts: float,
    on_current_amps: float,
) -> list[str]:
    """Return reasons why a sample should be persisted."""
    if previous is None:
        return ["initial_sample"]

    reasons: list[str] = []
    if _changed(
        measurement.get("current_rms"),
        previous.get("current_rms"),
        current_change_amps,
    ):
        reasons.append("current_change")
    if _changed(
        measurement.get("real_power"),
        previous.get("real_power"),
        power_change_watts,
    ):
        reasons.append("power_change")
    if _changed(
        measurement.get("voltage_rms"),
        previous.get("voltage_rms"),
        voltage_change_volts,
    ):
        reasons.append("voltage_change")

    current = measurement.get("current_rms")
    old_current = previous.get("current_rms")
    if current is not None and old_current is not None:
        is_on = float(current) >= on_current_amps
        was_on = float(old_current) >= on_current_amps
        if is_on != was_on:
            reasons.append("heater_on" if is_on else "heater_off")
    return reasons


def build_parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[1]
    output_directory = repository_root / "saved_data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=output_directory / "calibration",
    )
    parser.add_argument(
        "--duration-seconds",
        type=finite_positive,
        help="stop after this duration; otherwise run until signaled",
    )
    parser.add_argument(
        "--sample-interval-seconds",
        type=finite_positive,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=heartbeat_interval,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="maximum stable period between rows; minimum 60 seconds",
    )
    parser.add_argument(
        "--current-change-amps",
        type=nonnegative_float,
        default=DEFAULT_CURRENT_CHANGE_AMPS,
    )
    parser.add_argument(
        "--power-change-watts",
        type=nonnegative_float,
        default=DEFAULT_POWER_CHANGE_WATTS,
    )
    parser.add_argument(
        "--voltage-change-volts",
        type=nonnegative_float,
        default=DEFAULT_VOLTAGE_CHANGE_VOLTS,
    )
    parser.add_argument(
        "--on-current-amps",
        type=nonnegative_float,
        default=DEFAULT_ON_CURRENT_AMPS,
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="run the existing interactive calibration before monitoring",
    )
    return parser


def _default_output_path() -> Path:
    repository_root = Path(__file__).resolve().parents[1]
    filename = datetime.now(timezone.utc).strftime("power_data_%Y_%m_%d_%H%M%SZ.csv")
    return repository_root / "saved_data" / filename


def _measurement_row(
    measurement: dict[str, Any] | None,
    *,
    elapsed_seconds: float,
    status: str,
    reasons: list[str],
) -> dict[str, Any]:
    row = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "timestamp_utc": utc_timestamp(),
            "monitor_elapsed_seconds": f"{elapsed_seconds:.3f}",
            "status": status,
            "record_reason": "|".join(reasons),
        }
    )
    if measurement is not None:
        for column in CSV_COLUMNS[4:]:
            value = measurement.get(column)
            row[column] = "" if value is None else value
    return row


def run_monitor(args: argparse.Namespace, stop_event: threading.Event) -> int:
    # Hardware imports are intentionally deferred so parsing and unit tests work on Windows.
    from smbus2 import SMBus

    from helpers.hardware_map import I2C_BUS
    from helpers.helper_power_functions import (
        calibrate,
        get_calibration_from_JSON,
        read_measurement_values,
    )

    output_path = args.output_csv or _default_output_path()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    calibration_directory = args.calibration_dir.resolve()
    calibration = get_calibration_from_JSON(
        str(calibration_directory), str(output_path.parent)
    )

    start_monotonic = time.monotonic()
    last_record_monotonic = start_monotonic
    last_logged_measurement: dict[str, Any] | None = None
    i2c_error_active = False

    with SMBus(I2C_BUS) as bus, output_path.open(
        "x", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        handle.flush()

        if args.calibrate:
            calibrate(
                bus,
                calibration,
                str(calibration_directory),
                str(output_path.parent),
            )
            calibration = get_calibration_from_JSON(
                str(calibration_directory), str(output_path.parent)
            )

        print(
            "POWER_MONITOR_READY "
            + json.dumps({"output_csv": str(output_path), "timestamp_utc": utc_timestamp()}),
            flush=True,
        )

        while not stop_event.is_set():
            now_monotonic = time.monotonic()
            elapsed = now_monotonic - start_monotonic
            if args.duration_seconds is not None and elapsed >= args.duration_seconds:
                break

            measurement = read_measurement_values(bus, calibration)
            reasons: list[str] = []
            status = "ok"

            if measurement is None:
                status = "i2c_error"
                if not i2c_error_active:
                    reasons.append("i2c_error")
                    i2c_error_active = True
                elif now_monotonic - last_record_monotonic >= args.heartbeat_seconds:
                    reasons.append("heartbeat")
            else:
                if i2c_error_active:
                    reasons.append("i2c_recovered")
                    i2c_error_active = False
                reasons.extend(
                    measurement_change_reasons(
                        measurement,
                        last_logged_measurement,
                        current_change_amps=args.current_change_amps,
                        power_change_watts=args.power_change_watts,
                        voltage_change_volts=args.voltage_change_volts,
                        on_current_amps=args.on_current_amps,
                    )
                )
                if (
                    not reasons
                    and now_monotonic - last_record_monotonic >= args.heartbeat_seconds
                ):
                    reasons.append("heartbeat")

            if reasons:
                writer.writerow(
                    _measurement_row(
                        measurement,
                        elapsed_seconds=elapsed,
                        status=status,
                        reasons=reasons,
                    )
                )
                handle.flush()
                last_record_monotonic = now_monotonic
                if measurement is not None:
                    last_logged_measurement = dict(measurement)
                print(
                    "POWER_MONITOR_RECORD "
                    + json.dumps(
                        {
                            "timestamp_utc": utc_timestamp(),
                            "status": status,
                            "reasons": reasons,
                        }
                    ),
                    flush=True,
                )

            stop_event.wait(args.sample_interval_seconds)

    print(
        "POWER_MONITOR_STOPPED "
        + json.dumps({"output_csv": str(output_path), "timestamp_utc": utc_timestamp()}),
        flush=True,
    )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        return run_monitor(args, stop_event)
    except Exception as exc:
        print(f"POWER_MONITOR_ERROR {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
