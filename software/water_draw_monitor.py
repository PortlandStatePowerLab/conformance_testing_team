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
from pathlib import Path
from typing import Any

# Preserve direct-script execution in addition to the scheduler's module launch.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.cold_water.client import DEFAULT_SOCKET_PATH
from software.cold_water.station_sensor_source import (
    build_station_sensor_session,
)
from software.exception_notes import add_exception_note
from software.pacific_time import pacific_filename_timestamp, pacific_timestamp
from software.station.station_hardware_map import VALVE_PIN
from software.sensors import SensorSnapshot
from software.valve import build_gpio_valve


DEFAULT_SAMPLE_INTERVAL_SECONDS = 0.5
DEFAULT_MAX_RUN_MINUTES = 10.0
DEFAULT_LOW_FLOW_GPM = 0.05
DEFAULT_LOW_FLOW_TIMEOUT_SECONDS = 20.0
TEMP_ARM_FRACTION_OF_DROP = 2.0 / 3.0
TEMP_CONFIRMATION_SAMPLES = 20
MAX_INVALID_TEMP_SAMPLES = 20
TEMPERATURE_COMPARISON_EPSILON_F = 1e-6

EXIT_SUCCESS = 0
EXIT_MAX_RUNTIME = 2
EXIT_LOW_FLOW = 3
EXIT_SENSOR_ERROR = 4
EXIT_TERMINATED = 5

CSV_COLUMNS: tuple[str, ...] = (
    "event_id",
    "timestamp_pacific",
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
    "cold_source_station",
    "cold_source_timestamp_pacific",
)

TEMPERATURE_COLUMNS: tuple[str, ...] = (
    "hot_temp_c",
    "hot_temp_f",
    "cold_temp_c",
    "cold_temp_f",
    "ambient_temp_c",
    "ambient_temp_f",
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
    parser.add_argument(
        "--draw-type", choices=("volume", "cut_in", "temp_drop"), default="volume"
    )
    parser.add_argument("--target-gal", type=positive_float)
    parser.add_argument("--temp-set-f", type=float)
    parser.add_argument("--temp-drop-f", type=positive_float)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument(
        "--sensor-configuration",
        "--sensor-calibration",
        dest="sensor_configuration",
        type=Path,
        help=(
            "optional water-sensor configuration JSON; "
            "nominal values are used when omitted"
        ),
    )
    parser.add_argument("--station-number", type=int, choices=(1, 2, 3, 4))
    parser.add_argument(
        "--cold-water-socket",
        type=Path,
        default=DEFAULT_SOCKET_PATH,
    )
    parser.add_argument("--cold-water-host")
    parser.add_argument("--cold-water-user")
    parser.add_argument("--cold-water-identity-file", type=Path)
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


def validate_draw_arguments(args: argparse.Namespace) -> None:
    if args.draw_type == "volume" and args.target_gal is None:
        raise ValueError("Volume draw requires --target-gal")
    if args.draw_type == "temp_drop":
        if args.temp_set_f is None or not math.isfinite(args.temp_set_f):
            raise ValueError("Temp Drop draw requires finite --temp-set-f")
        if args.temp_drop_f is None:
            raise ValueError("Temp Drop draw requires --temp-drop-f")


def default_output_path(event_id: str, directory: Path) -> Path:
    safe_event_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in event_id
    )
    timestamp = pacific_filename_timestamp()
    return directory / f"water_draw_{safe_event_id}_{timestamp}.csv"


def integrate_volume_gallons(flow_gpm: float, elapsed_seconds: float) -> float:
    return max(flow_gpm, 0.0) * elapsed_seconds / 60.0


def temperature_arm_threshold_f(temp_set_f: float, temp_drop_f: float) -> float:
    """Return the unrounded temperature that arms Temp Drop shutdown logic."""
    return temp_set_f - temp_drop_f * TEMP_ARM_FRACTION_OF_DROP


def _row(
    *,
    event_id: str,
    elapsed_seconds: float,
    status: str,
    stop_reason: str,
    valve_state: str,
    target_volume_gal: float | None,
    volume_gal: float,
    snapshot: SensorSnapshot | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "event_id": event_id,
            "timestamp_pacific": pacific_timestamp(),
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
        row["flow_gpm"] = f"{snapshot.flow_gpm:.6f}"
        for field in TEMPERATURE_COLUMNS:
            row[field] = f"{getattr(snapshot, field):.2f}"
    return row


def run_draw(args: argparse.Namespace, stop_event: threading.Event) -> int:
    validate_draw_arguments(args)
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

        sensor_session = None
        valve = None
        volume_gal = 0.0
        last_snapshot = None
        start = 0.0
        previous_sample_time = 0.0
        low_flow_start: float | None = None
        temperature_armed = False
        stop_temp_count = 0
        invalid_temp_count = 0
        stop_reason = "sensor_error"
        exit_code = EXIT_SENSOR_ERROR

        try:
            valve = build_gpio_valve()

            sensor_session = build_station_sensor_session(
                configuration_path=args.sensor_configuration,
                active_station_number=args.station_number,
                socket_path=args.cold_water_socket,
                remote_host=args.cold_water_host,
                remote_user=args.cold_water_user,
                identity_file=args.cold_water_identity_file,
            )
            sensor_reader = sensor_session.reader
            # A fresh local/remote snapshot is required before valve actuation.
            sensor_reader.get_sensor_snapshot()
            print(
                "WATER_DRAW_READY "
                + json.dumps(
                    {
                        "event_id": args.event_id,
                        "output_csv": str(output_path),
                        "timestamp_pacific": pacific_timestamp(),
                        "draw_type": args.draw_type,
                        "temp_set_f": args.temp_set_f,
                        "temp_drop_f": args.temp_drop_f,
                        "stop_temp_f": (
                            args.temp_set_f - args.temp_drop_f
                            if args.draw_type == "temp_drop" else None
                        ),
                    }
                ),
                flush=True,
            )

            start = time.monotonic()
            previous_sample_time = start
            valve.open()
            print(
                "WATER_DRAW_VALVE_OPEN "
                + json.dumps(
                    {
                        "event_id": args.event_id,
                        "timestamp_pacific": pacific_timestamp(),
                    }
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
                    stop_reason = "time_limit_reached" if args.draw_type == "temp_drop" else "max_runtime"
                    exit_code = EXIT_SUCCESS if args.draw_type == "temp_drop" else EXIT_MAX_RUNTIME
                    break

                try:
                    snapshot = sensor_reader.get_sensor_snapshot()
                except Exception:
                    if args.draw_type != "temp_drop":
                        raise
                    invalid_temp_count += 1
                    if invalid_temp_count >= MAX_INVALID_TEMP_SAMPLES:
                        stop_reason = "temperature_sensor_unavailable"
                        exit_code = EXIT_SENSOR_ERROR
                        break
                    stop_event.wait(args.sample_interval_seconds)
                    continue
                last_snapshot = snapshot
                volume_gal += integrate_volume_gallons(
                    snapshot.flow_gpm, sample_delta
                )

                if args.draw_type == "temp_drop":
                    hot_temp_f = snapshot.hot_temp_f
                    if not math.isfinite(hot_temp_f):
                        invalid_temp_count += 1
                        if invalid_temp_count >= MAX_INVALID_TEMP_SAMPLES:
                            stop_reason = "temperature_sensor_unavailable"
                            exit_code = EXIT_SENSOR_ERROR
                    else:
                        invalid_temp_count = 0
                        arm_temp_f = temperature_arm_threshold_f(
                            args.temp_set_f, args.temp_drop_f
                        )
                        stop_temp_f = args.temp_set_f - args.temp_drop_f
                        if not temperature_armed and hot_temp_f >= arm_temp_f:
                            temperature_armed = True
                            print(
                                "WATER_DRAW_TEMP_ARMED "
                                + json.dumps(
                                    {
                                        "event_id": args.event_id,
                                        "hot_temp_f": hot_temp_f,
                                        "arm_temp_f": round(arm_temp_f, 1),
                                    }
                                ),
                                flush=True,
                            )
                        if temperature_armed:
                            stop_temp_count = (
                                stop_temp_count + 1
                                if hot_temp_f <= stop_temp_f + TEMPERATURE_COMPARISON_EPSILON_F
                                else 0
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
                if stop_reason == "temperature_sensor_unavailable":
                    break
                if args.draw_type == "volume" and volume_gal >= args.target_gal:
                    stop_reason = "target_reached"
                    exit_code = EXIT_SUCCESS
                    break
                if args.draw_type == "temp_drop" and stop_temp_count >= TEMP_CONFIRMATION_SAMPLES:
                    stop_reason = "temperature_threshold_reached"
                    exit_code = EXIT_SUCCESS
                    break
                stop_event.wait(args.sample_interval_seconds)
        finally:
            cleanup_error: BaseException | None = None
            if valve is not None:
                try:
                    valve.cleanup()
                except BaseException as error:
                    cleanup_error = error
            if sensor_session is not None:
                try:
                    sensor_session.close()
                except BaseException as error:
                    if cleanup_error is None:
                        cleanup_error = error
                    else:
                        add_exception_note(
                            cleanup_error,
                            f"Sensor session cleanup also failed: {error!r}"
                        )

            elapsed = time.monotonic() - start
            writer.writerow(
                _row(
                    event_id=args.event_id,
                    elapsed_seconds=elapsed,
                    status="completed" if exit_code == EXIT_SUCCESS else "stopped",
                    stop_reason=stop_reason,
                    valve_state="closed" if valve is not None else "not_configured",
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
                        "timestamp_pacific": pacific_timestamp(),
                        "stop_reason": stop_reason,
                        "volume_gal": volume_gal,
                        "final_hot_temp_f": (
                            last_snapshot.hot_temp_f if last_snapshot is not None else None
                        ),
                        "exit_code": exit_code,
                    }
                ),
                flush=True,
            )
            if cleanup_error is not None:
                raise cleanup_error
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
