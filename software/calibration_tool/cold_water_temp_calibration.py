#!/usr/bin/env python3
"""Calibrate WH-station1 cold-water temperature with three faucet checks."""

from __future__ import annotations

import argparse
import json
import selectors
import shutil
import socket
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from software.cold_water.station_sensor_source import build_station_sensor_session
from software.exception_notes import add_exception_note
from software.sensors import SensorSnapshot
from software.valve import build_gpio_valve


CHECK_COUNT = 3
CALIBRATION_TIMEOUT_SECONDS = 240.0
PACIFIC = ZoneInfo("America/Los_Angeles")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALIBRATION_DIRECTORY = REPOSITORY_ROOT / "saved_data" / "calibration"
STATION_NAME = "WH-station1"


class CalibrationTimedOut(RuntimeError):
    """Indicate that the valve-open calibration deadline expired."""


class SnapshotReader(Protocol):
    def get_sensor_snapshot(self) -> SensorSnapshot:
        """Return the current station sensor snapshot."""


ReferenceReader = Callable[[int, float], float]


@dataclass(frozen=True)
class ColdWaterCalibrationResult:
    reference_readings_f: tuple[float, ...]
    uncalibrated_readings_f: tuple[float, ...]
    raw_count_readings: tuple[int, ...]
    average_reference_temp_f: float
    average_uncalibrated_temp_f: float
    average_raw_counts: float
    correction_offset_f: float


def _mean(values: Sequence[float | int]) -> float:
    return sum(values) / len(values)


def calculate_cold_water_calibration(
    sensor_reader: SnapshotReader,
    reference_reader: ReferenceReader,
    *,
    deadline: float,
    monotonic: Callable[[], float] | None = None,
) -> ColdWaterCalibrationResult:
    """Capture three paired faucet-reference and cold-sensor readings."""
    clock = monotonic or time.monotonic
    references: list[float] = []
    sensor_temperatures: list[float] = []
    raw_counts: list[int] = []
    for check_number in range(1, CHECK_COUNT + 1):
        if clock() >= deadline:
            raise CalibrationTimedOut("cold-water calibration exceeded 240 seconds")
        reference_temp_f = float(reference_reader(check_number, deadline))
        if clock() >= deadline:
            raise CalibrationTimedOut("cold-water calibration exceeded 240 seconds")
        snapshot = sensor_reader.get_sensor_snapshot()
        references.append(reference_temp_f)
        sensor_temperatures.append(float(snapshot.cold_temp_f))
        raw_counts.append(int(snapshot.cold_raw_counts))

    average_reference = _mean(references)
    average_sensor = _mean(sensor_temperatures)
    return ColdWaterCalibrationResult(
        reference_readings_f=tuple(references),
        uncalibrated_readings_f=tuple(sensor_temperatures),
        raw_count_readings=tuple(raw_counts),
        average_reference_temp_f=average_reference,
        average_uncalibrated_temp_f=average_sensor,
        average_raw_counts=_mean(raw_counts),
        correction_offset_f=average_reference - average_sensor,
    )


def calibration_section(
    result: ColdWaterCalibrationResult,
    *,
    calibrated_at: datetime | None = None,
) -> dict[str, object]:
    timestamp = calibrated_at or datetime.now(PACIFIC)
    return {
        "method": "three_reading_average_offset",
        "correction_offset_f": round(result.correction_offset_f, 3),
        "average_reference_temp_f": round(result.average_reference_temp_f, 3),
        "average_uncalibrated_temp_f": round(
            result.average_uncalibrated_temp_f, 3
        ),
        "average_raw_counts": round(result.average_raw_counts, 3),
        "reference_readings_f": [round(value, 3) for value in result.reference_readings_f],
        "uncalibrated_readings_f": [
            round(value, 3) for value in result.uncalibrated_readings_f
        ],
        "raw_count_readings": list(result.raw_count_readings),
        "thermometer_used": "Bomata T101A",
        "thermometer_accuracy_f": 1.8,
        "last_cal_time": timestamp.isoformat(timespec="seconds"),
    }


def save_cold_water_calibration(
    calibration_path: Path,
    section: dict[str, object],
    *,
    saved_at: datetime | None = None,
) -> Path | None:
    """Back up and atomically update only ``cold_water_temp``."""
    timestamp = saved_at or datetime.now(PACIFIC)
    document: dict[str, object] = {}
    backup_path: Path | None = None
    if calibration_path.exists():
        loaded = json.loads(calibration_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("station calibration JSON must contain an object")
        document = loaded
        suffix = timestamp.strftime("%Y_%m_%d_%H%M%S_%z")
        backup_path = calibration_path.with_name(
            f"{calibration_path.stem}_{suffix}.json.save"
        )
        shutil.copy2(calibration_path, backup_path)

    document["cold_water_temp"] = section
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=calibration_path.parent,
            prefix=f".{calibration_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(document, handle, indent=2)
            handle.write("\n")
            handle.flush()
        json.loads(temporary_path.read_text(encoding="utf-8"))
        temporary_path.replace(calibration_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return backup_path


def confirm_faucet_ready() -> None:
    input(
        "Open the cold-only faucet and match approximately the WH-1 flow. "
        "Press Enter when both streams are running..."
    )


def console_reference_reader(check_number: int, deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise CalibrationTimedOut("cold-water calibration exceeded 240 seconds")
    print(
        f"Check {check_number}/{CHECK_COUNT}: enter Bomata T101A faucet temperature in °F: ",
        end="",
        flush=True,
    )
    selector = selectors.DefaultSelector()
    try:
        selector.register(sys.stdin, selectors.EVENT_READ)
        if not selector.select(remaining):
            print()
            raise CalibrationTimedOut("cold-water calibration exceeded 240 seconds")
        text = sys.stdin.readline()
    finally:
        selector.close()
    if text == "":
        raise EOFError("standard input closed during cold-water calibration")
    return float(text.strip())


def default_station_name() -> str:
    hostname = socket.gethostname()
    if hostname != STATION_NAME:
        raise ValueError("cold-water calibration may run only on WH-station1")
    return hostname


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calibrate the shared WH-station1 cold-water sensor."
    )
    parser.add_argument("--station", help="must be WH-station1")
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=DEFAULT_CALIBRATION_DIRECTORY,
    )
    return parser


def run(args: argparse.Namespace) -> int:
    station_name = args.station or default_station_name()
    if station_name != STATION_NAME:
        raise ValueError("cold-water calibration may run only on WH-station1")
    calibration_path = args.calibration_dir / f"{STATION_NAME}.json"

    valve = None
    sensor_session = None
    faucet_started = False
    active_error: BaseException | None = None
    try:
        valve = build_gpio_valve()
        sensor_session = build_station_sensor_session(
            active_station_number=1,
            apply_hot_water_calibration=False,
        )
        sensor_session.reader.get_sensor_snapshot()
        confirm_faucet_ready()
        faucet_started = True
        valve.open()
        deadline = time.monotonic() + CALIBRATION_TIMEOUT_SECONDS
        print("WH-1 valve open. Complete all three checks within four minutes.")
        result = calculate_cold_water_calibration(
            sensor_session.reader,
            console_reference_reader,
            deadline=deadline,
        )
        valve.close()
        section = calibration_section(result)
        backup = save_cold_water_calibration(calibration_path, section)
        print("WH-1 valve closed. Close the cold faucet.")
        print(f"Average reference: {result.average_reference_temp_f:.2f} °F")
        print(f"Average sensor: {result.average_uncalibrated_temp_f:.2f} °F")
        print(f"Correction offset: {result.correction_offset_f:+.2f} °F")
        if backup is not None:
            print(f"Previous calibration saved to {backup}")
        print(f"Calibration saved to {calibration_path}")
        return 0
    except BaseException as error:
        active_error = error
        raise
    finally:
        if valve is not None:
            try:
                valve.cleanup()
            except BaseException as cleanup_error:
                if active_error is None:
                    raise
                add_exception_note(active_error, f"Valve cleanup also failed: {cleanup_error!r}")
        if sensor_session is not None:
            try:
                sensor_session.close()
            except BaseException as cleanup_error:
                if active_error is None:
                    raise
                add_exception_note(active_error, f"Sensor cleanup also failed: {cleanup_error!r}")
        if faucet_started and active_error is not None:
            print("WH-1 valve secured. Close the cold faucet.")


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
