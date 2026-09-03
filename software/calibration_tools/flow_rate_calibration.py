#!/usr/bin/env python3
"""Calibrate one station flow channel at zero and its normal flow rate."""

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
from zoneinfo import ZoneInfo

from software.exception_notes import add_exception_note
from software.sensors import SensorReader
from software.station.station_adc_builder import build_station_adc
from software.valve import build_gpio_valve


ZERO_SAMPLE_COUNT = 20
ZERO_SAMPLE_INTERVAL_SECONDS = 0.5
FLOW_SAMPLE_COUNT = 5
FLOW_SAMPLE_INTERVAL_SECONDS = 0.2
REFERENCE_CHECK_COUNT = 3
CALIBRATION_TIMEOUT_SECONDS = 240.0
REFERENCE_DEVICE = "McMaster-Carr SBN234"
PACIFIC = ZoneInfo("America/Los_Angeles")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALIBRATION_DIRECTORY = REPOSITORY_ROOT / "saved_data" / "calibration"


class CalibrationTimedOut(RuntimeError):
    """Indicate that the valve-open calibration deadline expired."""


ReferenceReader = Callable[[int, float], float]


@dataclass(frozen=True)
class FlowSample:
    average_raw_counts: float
    average_uncalibrated_gpm: float


@dataclass(frozen=True)
class FlowCalibrationResult:
    zero_raw_count_readings: tuple[int, ...]
    zero_uncalibrated_gpm_readings: tuple[float, ...]
    reference_readings_gpm: tuple[float, ...]
    flowing_raw_count_averages: tuple[float, ...]
    uncalibrated_readings_gpm: tuple[float, ...]
    zero_raw_counts: float
    zero_raw_max_counts: int
    average_reference_gpm: float
    average_flowing_raw_counts: float
    average_uncalibrated_gpm: float
    scale_gpm_per_count: float
    offset_gpm: float


def _mean(values: Sequence[float | int]) -> float:
    return sum(values) / len(values)


def capture_flow_sample(
    sensor_reader,
    *,
    sample_count: int,
    sample_interval_seconds: float,
    deadline: float | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[FlowSample, tuple[int, ...], tuple[float, ...]]:
    """Average a short group of raw and nominal flow readings."""
    clock = monotonic or time.monotonic
    raw_counts: list[int] = []
    flow_values: list[float] = []
    for index in range(sample_count):
        if deadline is not None and clock() >= deadline:
            raise CalibrationTimedOut("flow calibration exceeded 240 seconds")
        snapshot = sensor_reader.get_sensor_snapshot()
        raw_counts.append(int(snapshot.flow_raw_counts))
        flow_values.append(float(snapshot.flow_gpm))
        if index + 1 < sample_count:
            sleep(sample_interval_seconds)
    return (
        FlowSample(_mean(raw_counts), _mean(flow_values)),
        tuple(raw_counts),
        tuple(flow_values),
    )


def calculate_flow_calibration(
    zero_raw_counts: Sequence[int],
    zero_uncalibrated_gpm: Sequence[float],
    reference_readings_gpm: Sequence[float],
    flowing_samples: Sequence[FlowSample],
) -> FlowCalibrationResult:
    """Calculate a two-point raw-count line from zero and normal flow."""
    if not (
        len(reference_readings_gpm) == REFERENCE_CHECK_COUNT
        and len(flowing_samples) == REFERENCE_CHECK_COUNT
    ):
        raise ValueError("flow calibration requires three flowing checks")
    zero_average = _mean(zero_raw_counts)
    flowing_raw = tuple(sample.average_raw_counts for sample in flowing_samples)
    uncalibrated = tuple(
        sample.average_uncalibrated_gpm for sample in flowing_samples
    )
    flowing_average = _mean(flowing_raw)
    count_difference = flowing_average - zero_average
    reference_average = _mean(reference_readings_gpm)
    if count_difference <= 10.0:
        raise ValueError("flowing raw counts are too close to the zero-flow baseline")
    if reference_average <= 0.0:
        raise ValueError("reference flow must be greater than zero")
    scale = reference_average / count_difference
    return FlowCalibrationResult(
        zero_raw_count_readings=tuple(int(value) for value in zero_raw_counts),
        zero_uncalibrated_gpm_readings=tuple(
            float(value) for value in zero_uncalibrated_gpm
        ),
        reference_readings_gpm=tuple(float(value) for value in reference_readings_gpm),
        flowing_raw_count_averages=flowing_raw,
        uncalibrated_readings_gpm=uncalibrated,
        zero_raw_counts=zero_average,
        zero_raw_max_counts=max(zero_raw_counts),
        average_reference_gpm=reference_average,
        average_flowing_raw_counts=flowing_average,
        average_uncalibrated_gpm=_mean(uncalibrated),
        scale_gpm_per_count=scale,
        offset_gpm=-zero_average * scale,
    )


def calibration_section(
    result: FlowCalibrationResult,
    *,
    calibrated_at: datetime | None = None,
) -> dict[str, object]:
    timestamp = calibrated_at or datetime.now(PACIFIC)
    return {
        "method": "zero_and_three_reading_average_scale",
        "scale_gpm_per_count": round(result.scale_gpm_per_count, 9),
        "offset_gpm": round(result.offset_gpm, 6),
        "zero_raw_counts": round(result.zero_raw_counts, 3),
        "zero_raw_max_counts": result.zero_raw_max_counts,
        "average_reference_gpm": round(result.average_reference_gpm, 4),
        "average_flowing_raw_counts": round(
            result.average_flowing_raw_counts, 3
        ),
        "average_uncalibrated_gpm": round(
            result.average_uncalibrated_gpm, 4
        ),
        "zero_raw_count_readings": list(result.zero_raw_count_readings),
        "zero_uncalibrated_gpm_readings": [
            round(value, 6) for value in result.zero_uncalibrated_gpm_readings
        ],
        "reference_readings_gpm": [
            round(value, 4) for value in result.reference_readings_gpm
        ],
        "flowing_raw_count_averages": [
            round(value, 3) for value in result.flowing_raw_count_averages
        ],
        "uncalibrated_readings_gpm": [
            round(value, 6) for value in result.uncalibrated_readings_gpm
        ],
        "reference_device": REFERENCE_DEVICE,
        "last_cal_time": timestamp.isoformat(timespec="seconds"),
    }


def save_flow_calibration(
    calibration_path: Path,
    section: dict[str, object],
    *,
    saved_at: datetime | None = None,
) -> Path | None:
    """Back up and atomically update only ``flow_rate``."""
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
    document["flow_rate"] = section
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
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise CalibrationTimedOut("flow calibration exceeded 240 seconds")
    print(
        f"Check {check_number}/{REFERENCE_CHECK_COUNT}: "
        f"enter {REFERENCE_DEVICE} display reading in GPM: ",
        end="",
        flush=True,
    )
    selector = selectors.DefaultSelector()
    try:
        selector.register(sys.stdin, selectors.EVENT_READ)
        if not selector.select(remaining):
            print()
            raise CalibrationTimedOut("flow calibration exceeded 240 seconds")
        text = sys.stdin.readline()
    finally:
        selector.close()
    if text == "":
        raise EOFError("standard input closed during flow calibration")
    return float(text.strip())


def default_station_name() -> str:
    hostname = socket.gethostname()
    if re.fullmatch(r"WH-station[1-4]", hostname) is None:
        raise ValueError(
            "hostname must use WH-station1 through WH-station4, or --station must be supplied"
        )
    return hostname


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calibrate a station flow sensor against its SBN234 display."
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
        raise ValueError("station must be WH-station1 through WH-station4")
    calibration_path = args.calibration_dir / f"{station_name}.json"

    valve = None
    adc = None
    active_error: BaseException | None = None
    try:
        valve = build_gpio_valve()
        adc = build_station_adc()
        sensor_reader = SensorReader(
            adc,
            apply_hot_water_calibration=False,
            apply_cold_water_calibration=False,
        )
        sensor_reader.get_sensor_snapshot()
        print(
            f"Capturing {ZERO_SAMPLE_COUNT} zero-flow samples with the valve closed..."
        )
        zero_sample, zero_raw, zero_gpm = capture_flow_sample(
            sensor_reader,
            sample_count=ZERO_SAMPLE_COUNT,
            sample_interval_seconds=ZERO_SAMPLE_INTERVAL_SECONDS,
        )
        print(
            f"Zero raw average: {zero_sample.average_raw_counts:.3f} counts; "
            f"range {min(zero_raw)}-{max(zero_raw)}; "
            f"hex range 0x{min(zero_raw):03X}-0x{max(zero_raw):03X}"
        )
        print(
            f"Zero nominal flow average: "
            f"{zero_sample.average_uncalibrated_gpm:.4f} GPM"
        )
        input("Press Enter to open the valve and begin the flowing checks...")
        valve.open()
        deadline = time.monotonic() + CALIBRATION_TIMEOUT_SECONDS
        print("Valve open. Complete all three checks within four minutes.")

        references: list[float] = []
        flowing_samples: list[FlowSample] = []
        for check_number in range(1, REFERENCE_CHECK_COUNT + 1):
            reference = console_reference_reader(check_number, deadline)
            if reference <= 0.0:
                raise ValueError("reference flow must be greater than zero")
            sample, _, _ = capture_flow_sample(
                sensor_reader,
                sample_count=FLOW_SAMPLE_COUNT,
                sample_interval_seconds=FLOW_SAMPLE_INTERVAL_SECONDS,
                deadline=deadline,
            )
            references.append(reference)
            flowing_samples.append(sample)
            print(
                f"  sensor={sample.average_uncalibrated_gpm:.4f} GPM, "
                f"raw={sample.average_raw_counts:.1f} counts "
                f"(0x{round(sample.average_raw_counts):03X})"
            )

        valve.close()
        result = calculate_flow_calibration(
            zero_raw,
            zero_gpm,
            references,
            flowing_samples,
        )
        section = calibration_section(result)
        backup = save_flow_calibration(calibration_path, section)
        print(f"Average meter flow: {result.average_reference_gpm:.3f} GPM")
        print(
            f"Average uncalibrated flow: "
            f"{result.average_uncalibrated_gpm:.3f} GPM"
        )
        print(f"Scale: {result.scale_gpm_per_count:.9f} GPM/count")
        print(f"Offset: {result.offset_gpm:+.6f} GPM")
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
        if adc is not None:
            try:
                adc.close()
            except BaseException as cleanup_error:
                if active_error is None:
                    raise
                add_exception_note(active_error, f"ADC cleanup also failed: {cleanup_error!r}")


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
