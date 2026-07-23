#!/usr/bin/env python3
"""Fail-safe, CSV-logging water draw adapted from Blake's WHS script."""

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

try:
    from .helpers.hardware_map import MAX1238_I2C_ADDR, MAX1238_I2C_BUS, VALVE_PIN
except ImportError:
    from helpers.hardware_map import MAX1238_I2C_ADDR, MAX1238_I2C_BUS, VALVE_PIN


DEFAULT_SAMPLE_INTERVAL_SECONDS = 0.5
DEFAULT_MAX_RUN_MINUTES = 10.0
DEFAULT_LOW_FLOW_GPM = 0.05
DEFAULT_LOW_FLOW_TIMEOUT_SECONDS = 20.0

EXIT_SUCCESS = 0
EXIT_MAX_RUNTIME = 2
EXIT_LOW_FLOW = 3
EXIT_SENSOR_ERROR = 4
EXIT_TERMINATED = 5

CSV_COLUMNS = (
    "event_id",
    "timestamp_utc",
    "draw_elapsed_seconds",
    "status",
    "stop_reason",
    "valve_state",
    "target_volume_gal",
    "accumulated_volume_gal",
    "flow_gpm",
    "hot_temp_c",
    "hot_temp_f",
    "cold_temp_c",
    "cold_temp_f",
    "ambient_temp_c",
    "ambient_temp_f",
    "hot_raw_counts",
    "cold_raw_counts",
    "flow_raw_counts",
    "ambient_raw_counts",
)


def utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite number zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--target-gal", required=True, type=positive_float)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--sensor-calibration", type=Path)
    parser.add_argument(
        "--sample-interval-seconds",
        type=positive_float,
        default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--max-run-minutes",
        type=positive_float,
        default=DEFAULT_MAX_RUN_MINUTES,
    )
    parser.add_argument(
        "--low-flow-gpm",
        type=nonnegative_float,
        default=DEFAULT_LOW_FLOW_GPM,
    )
    parser.add_argument(
        "--low-flow-timeout-seconds",
        type=positive_float,
        default=DEFAULT_LOW_FLOW_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--enable-output",
        action="store_true",
        help=f"actually actuate GPIO{VALVE_PIN}; dry-run by default",
    )
    parser.set_defaults(default_output_directory=repository_root / "saved_data")
    return parser


def default_output_path(event_id: str, directory: Path) -> Path:
    safe_event_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in event_id
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y_%m_%d_%H%M%SZ")
    return directory / f"water_draw_{safe_event_id}_{timestamp}.csv"


def integrate_volume_gallons(flow_gpm: float, elapsed_seconds: float) -> float:
    return max(flow_gpm, 0.0) * elapsed_seconds / 60.0


def _row(
    *,
    event_id: str,
    elapsed_seconds: float,
    status: str,
    stop_reason: str,
    valve_state: str,
    target_volume_gal: float,
    volume_gal: float,
    snapshot: Any | None,
) -> dict[str, Any]:
    row = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "event_id": event_id,
            "timestamp_utc": utc_timestamp(),
            "draw_elapsed_seconds": f"{elapsed_seconds:.3f}",
            "status": status,
            "stop_reason": stop_reason,
            "valve_state": valve_state,
            "target_volume_gal": target_volume_gal,
            "accumulated_volume_gal": f"{volume_gal:.6f}",
        }
    )
    if snapshot is not None:
        for field in CSV_COLUMNS[8:]:
            row[field] = getattr(snapshot, field)
    return row


def run_draw(args: argparse.Namespace, stop_event: threading.Event) -> int:
    output_path = args.output_csv or default_output_path(
        args.event_id, args.default_output_directory
    )
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        handle.flush()

        if not args.enable_output:
            writer.writerow(
                _row(
                    event_id=args.event_id,
                    elapsed_seconds=0.0,
                    status="dry_run",
                    stop_reason="output_disabled",
                    valve_state="not_configured",
                    target_volume_gal=args.target_gal,
                    volume_gal=0.0,
                    snapshot=None,
                )
            )
            handle.flush()
            print(
                "WATER_DRAW_DRY_RUN "
                + json.dumps(
                    {
                        "event_id": args.event_id,
                        "output_csv": str(output_path),
                        "target_gal": args.target_gal,
                    }
                ),
                flush=True,
            )
            return EXIT_SUCCESS

        # Hardware imports occur only after explicit output authorization.
        import RPi.GPIO as GPIO

        try:
            from .helpers.max1238_adc import Max1238Adc
            from .helpers.water_sensor_reader import WaterSensorReader
        except ImportError:
            from helpers.max1238_adc import Max1238Adc
            from helpers.water_sensor_reader import WaterSensorReader

        adc = None
        valve_configured = False
        volume_gal = 0.0
        last_snapshot = None
        start = time.monotonic()
        previous_sample_time = start
        low_flow_start: float | None = None
        stop_reason = "sensor_error"
        exit_code = EXIT_SENSOR_ERROR

        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(VALVE_PIN, GPIO.OUT, initial=GPIO.LOW)
            valve_configured = True

            adc = Max1238Adc(
                address=MAX1238_I2C_ADDR,
                bus_number=MAX1238_I2C_BUS,
            )
            adc.setup()
            sensor_reader = WaterSensorReader(
                adc, calibration_path=args.sensor_calibration
            )
            print(
                "WATER_DRAW_READY "
                + json.dumps(
                    {
                        "event_id": args.event_id,
                        "output_csv": str(output_path),
                        "timestamp_utc": utc_timestamp(),
                    }
                ),
                flush=True,
            )

            GPIO.output(VALVE_PIN, GPIO.HIGH)
            print(
                "WATER_DRAW_VALVE_OPEN "
                + json.dumps(
                    {"event_id": args.event_id, "timestamp_utc": utc_timestamp()}
                ),
                flush=True,
            )

            while True:
                sample_time = time.monotonic()
                elapsed = sample_time - start
                sample_delta = sample_time - previous_sample_time
                previous_sample_time = sample_time

                if stop_event.is_set():
                    stop_reason = "terminated"
                    exit_code = EXIT_TERMINATED
                    break
                if elapsed >= args.max_run_minutes * 60.0:
                    stop_reason = "max_runtime"
                    exit_code = EXIT_MAX_RUNTIME
                    break

                try:
                    snapshot = sensor_reader.snapshot()
                except Exception as exc:
                    stop_reason = f"sensor_error:{type(exc).__name__}"
                    exit_code = EXIT_SENSOR_ERROR
                    break
                last_snapshot = snapshot
                volume_gal += integrate_volume_gallons(
                    snapshot.flow_gpm, sample_delta
                )

                if snapshot.flow_gpm < args.low_flow_gpm:
                    if low_flow_start is None:
                        low_flow_start = sample_time
                    elif sample_time - low_flow_start >= args.low_flow_timeout_seconds:
                        stop_reason = "low_flow"
                        exit_code = EXIT_LOW_FLOW
                else:
                    low_flow_start = None

                writer.writerow(
                    _row(
                        event_id=args.event_id,
                        elapsed_seconds=elapsed,
                        status="drawing",
                        stop_reason="",
                        valve_state="open",
                        target_volume_gal=args.target_gal,
                        volume_gal=volume_gal,
                        snapshot=snapshot,
                    )
                )
                handle.flush()

                if exit_code == EXIT_LOW_FLOW:
                    break
                if volume_gal >= args.target_gal:
                    stop_reason = "target_reached"
                    exit_code = EXIT_SUCCESS
                    break
                stop_event.wait(args.sample_interval_seconds)
        finally:
            if valve_configured:
                try:
                    GPIO.output(VALVE_PIN, GPIO.LOW)
                finally:
                    GPIO.cleanup(VALVE_PIN)
            if adc is not None:
                adc.close()

            elapsed = time.monotonic() - start
            writer.writerow(
                _row(
                    event_id=args.event_id,
                    elapsed_seconds=elapsed,
                    status="completed" if exit_code == EXIT_SUCCESS else "stopped",
                    stop_reason=stop_reason,
                    valve_state="closed" if valve_configured else "not_configured",
                    target_volume_gal=args.target_gal,
                    volume_gal=volume_gal,
                    snapshot=last_snapshot,
                )
            )
            handle.flush()
            print(
                "WATER_DRAW_STOPPED "
                + json.dumps(
                    {
                        "event_id": args.event_id,
                        "timestamp_utc": utc_timestamp(),
                        "stop_reason": stop_reason,
                        "volume_gal": volume_gal,
                        "exit_code": exit_code,
                    }
                ),
                flush=True,
            )
        return exit_code


def main() -> int:
    args = build_parser().parse_args()
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        return run_draw(args, stop_event)
    except Exception as exc:
        print(f"WATER_DRAW_ERROR {exc}", file=sys.stderr, flush=True)
        return EXIT_SENSOR_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
