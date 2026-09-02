"""Calibrate station hot-water temperature with three reference checks."""

from __future__ import annotations

import argparse
import json
import re
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
from software.valve import Valve, build_gpio_valve


CHECK_COUNT = 3
CALIBRATION_TIMEOUT_SECONDS = 120.0
PACIFIC = ZoneInfo("America/Los_Angeles")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALIBRATION_DIRECTORY = REPOSITORY_ROOT / "saved_data" / "calibration"


class CalibrationTimedOut(RuntimeError):
    """Indicate that the valve-open calibration deadline expired."""


class SnapshotReader(Protocol):
    def get_sensor_snapshot(self) -> SensorSnapshot:
        """Return the current station sensor snapshot."""


ReferenceReader = Callable[[int, float], float]


@dataclass(frozen=True)
class HotWaterCalibrationResult:
    """Store the three-check hot-water offset calculation."""

    reference_readings_f: tuple[float, ...]
    uncalibrated_readings_f: tuple[float, ...]
    raw_count_readings: tuple[int, ...]
    average_reference_temp_f: float
    average_uncalibrated_temp_f: float
    average_raw_counts: float
    correction_offset_f: float


def _mean(values: Sequence[float | int]) -> float:
    return sum(values) / len(values)


def calculate_hot_water_calibration(
    sensor_reader: SnapshotReader,
    reference_reader: ReferenceReader,
    *,
    deadline: float,
    monotonic: Callable[[], float] | None = None,
) -> HotWaterCalibrationResult:
    """Capture three paired reference/sensor readings before ``deadline``."""
    clock = monotonic or time.monotonic
    references: list[float] = []
    sensor_temperatures: list[float] = []
    raw_counts: list[int] = []

    for check_number in range(1, CHECK_COUNT + 1):
        if clock() >= deadline:
            raise CalibrationTimedOut("hot-water calibration exceeded 120 seconds")
        reference_temp_f = float(reference_reader(check_number, deadline))
        if clock() >= deadline:
            raise CalibrationTimedOut("hot-water calibration exceeded 120 seconds")
        snapshot = sensor_reader.get_sensor_snapshot()
        references.append(reference_temp_f)
        sensor_temperatures.append(float(snapshot.hot_temp_f))
        raw_counts.append(int(snapshot.hot_raw_counts))

    average_reference = _mean(references)
    average_sensor = _mean(sensor_temperatures)
    return HotWaterCalibrationResult(
        reference_readings_f=tuple(references),
        uncalibrated_readings_f=tuple(sensor_temperatures),
        raw_count_readings=tuple(raw_counts),
        average_reference_temp_f=average_reference,
        average_uncalibrated_temp_f=average_sensor,
        average_raw_counts=_mean(raw_counts),
        correction_offset_f=average_reference - average_sensor,
    )


def calibration_section(
    result: HotWaterCalibrationResult,
    *,
    calibrated_at: datetime | None = None,
) -> dict[str, object]:
    """Build the persisted hot-water calibration section."""
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


def _backup_path(path: Path, timestamp: datetime) -> Path:
    suffix = timestamp.strftime("%Y_%m_%d_%H%M%S_%z")
    return path.with_name(f"{path.stem}_{suffix}.json.save")


def save_hot_water_calibration(
    calibration_path: Path,
    section: dict[str, object],
    *,
    saved_at: datetime | None = None,
) -> Path | None:
    """Back up and atomically update only ``hot_water_temp`` in a station file."""
    timestamp = saved_at or datetime.now(PACIFIC)
    document: dict[str, object] = {}
    backup_path: Path | None = None
    if calibration_path.exists():
        loaded = json.loads(calibration_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("station calibration JSON must contain an object")
        document = loaded
        backup_path = _backup_path(calibration_path, timestamp)
        shutil.copy2(calibration_path, backup_path)

    document["hot_water_temp"] = section
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


def console_reference_reader(check_number: int, deadline: float) -> float:
    """Read one thermometer value from stdin without exceeding the deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise CalibrationTimedOut("hot-water calibration exceeded 120 seconds")
    print(
        f"Check {check_number}/{CHECK_COUNT}: enter Bomata T101A temperature in °F: ",
        end="",
        flush=True,
    )
    selector = selectors.DefaultSelector()
    try:
        selector.register(sys.stdin, selectors.EVENT_READ)
        if not selector.select(remaining):
            print()
            raise CalibrationTimedOut("hot-water calibration exceeded 120 seconds")
        text = sys.stdin.readline()
    finally:
        selector.close()
    if text == "":
        raise EOFError("standard input closed during hot-water calibration")
    return float(text.strip())


def default_station_name() -> str:
    hostname = socket.gethostname()
    if re.fullmatch(r"WH-station[1-4]", hostname) is None:
        raise ValueError(
            "hostname must use the WH-station<number> format or --station must be supplied"
        )
    return hostname


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calibrate the station hot-water temperature sensor."
    )
    parser.add_argument("--station", help="station name, for example WH-station3")
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=DEFAULT_CALIBRATION_DIRECTORY,
    )
    return parser


def run(args: argparse.Namespace) -> int:
    station_name = args.station or default_station_name()
    if re.fullmatch(r"WH-station[1-4]", station_name) is None:
        raise ValueError("station must be WH-station1, WH-station2, WH-station3, or WH-station4")
    station_number = int(station_name[-1])
    calibration_path = args.calibration_dir / f"{station_name}.json"

    valve = None
    sensor_session = None
    active_error: BaseException | None = None
    try:
        valve = build_gpio_valve()
        sensor_session = build_station_sensor_session(
            active_station_number=station_number
        )
        sensor_session.reader.get_sensor_snapshot()
        valve.open()
        deadline = time.monotonic() + CALIBRATION_TIMEOUT_SECONDS
        print("Valve open. Complete all three checks within two minutes.")
        result = calculate_hot_water_calibration(
            sensor_session.reader,
            console_reference_reader,
            deadline=deadline,
        )
        valve.close()
        section = calibration_section(result)
        backup = save_hot_water_calibration(calibration_path, section)
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


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
