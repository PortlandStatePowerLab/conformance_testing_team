#!/usr/bin/env python3
"""Verify station prerequisites without opening the water valve."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.conformance_test_runner import (
    DEFAULT_CANONICAL_SCHEDULE,
    DEFAULT_CTA_BINARY,
    DEFAULT_RESULTS_ROOT,
)
from software.cold_water.station_sensor_source import (
    build_station_sensor_session,
)
from software.schedule_parser import load_schedule
from software.sensors.sensor_configuration_loader import (
    load_sensor_configuration,
)
from software.station.station_hardware_map import (
    ACS37800_I2C_ADDR,
    MAX1238_I2C_ADDR,
    MAX1238_I2C_BUS,
    VALVE_PIN,
)
from software.station.station_identity import station_number, station_results_directory

DEFAULT_SERIAL_PORT = Path("/dev/ttyUSB0")


@dataclass(frozen=True)
class PreflightCheck:
    """One independently reportable station prerequisite."""

    name: str
    passed: bool
    details: str


def _check(name: str, action) -> PreflightCheck:
    try:
        details = action()
        return PreflightCheck(name, True, str(details))
    except BaseException as error:
        return PreflightCheck(name, False, f"{type(error).__name__}: {error}")


def _require_linux() -> str:
    if not sys.platform.startswith("linux"):
        raise RuntimeError(f"station hardware requires Linux; found {sys.platform}")
    return sys.platform


def _require_module(module_name: str) -> str:
    importlib.import_module(module_name)
    return f"{module_name} available"


def _require_executable(path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    if not os.access(resolved, os.X_OK):
        raise PermissionError(f"not executable: {resolved}")
    return str(resolved)


def _require_device_access(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    if not os.access(path, os.R_OK | os.W_OK):
        raise PermissionError(f"read/write access required: {path}")
    return str(path)


def _require_results_write(results_root: Path) -> str:
    resolved = results_root.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=".preflight_",
        dir=resolved,
        delete=True,
        encoding="utf-8",
    ) as handle:
        handle.write("preflight\n")
        handle.flush()
    return str(resolved)


def _schedule_details(schedule_path: Path, require_water: bool) -> str:
    events = load_schedule(schedule_path)
    draws = [event for event in events if event.event_type == "water_draw"]
    if require_water and not draws:
        raise ValueError("water output requested but schedule has no water draws")
    return f"{len(events)} enabled events; {len(draws)} water draw(s)"


def _sensor_configuration_details(configuration_path: Path | None) -> str:
    load_sensor_configuration(configuration_path)
    if configuration_path is None:
        return "nominal sensor configuration"
    return str(configuration_path.resolve())


def _power_configuration_details(calibration_directory: Path) -> str:
    match = re.search(r"(\d+)$", socket.gethostname())
    if match is None:
        raise ValueError("hostname must end with a station number")
    path = calibration_directory / f"WH-station{match.group(1)}.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"vrms_scale", "irms_scale", "vrms_offset", "irms_offset"}
    missing = sorted(required.difference(data))
    if missing:
        raise ValueError(f"missing power configuration fields: {missing}")
    return str(path.resolve())


def _i2c_device_details(bus: int, address: int) -> str:
    executable = shutil.which("i2cdetect")
    if executable is None:
        raise FileNotFoundError("i2cdetect is not installed")
    completed = subprocess.run(
        [
            executable,
            "-y",
            "-r",
            str(bus),
            f"0x{address:02x}",
            f"0x{address:02x}",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(message or f"i2cdetect exited {completed.returncode}")
    tokens = completed.stdout.lower().split()
    expected = f"{address:02x}"
    if expected not in tokens and "uu" not in tokens:
        raise RuntimeError(f"no response at 0x{address:02x} on I2C bus {bus}")
    return f"/dev/i2c-{bus} address 0x{address:02x} responded"


def _gpio_low_details() -> str:
    gpio = importlib.import_module("RPi.GPIO")
    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    try:
        gpio.setup(VALVE_PIN, gpio.OUT, initial=gpio.LOW)
        if gpio.input(VALVE_PIN) != gpio.LOW:
            raise RuntimeError(f"GPIO{VALVE_PIN} did not read LOW")
    finally:
        gpio.cleanup(VALVE_PIN)
    return f"GPIO{VALVE_PIN} initialized LOW and released"


def _station_sensor_details(configuration_path: Path | None) -> str:
    number = station_number()
    session = build_station_sensor_session(
        configuration_path=configuration_path,
        active_station_number=number,
    )
    try:
        snapshot = session.reader.get_sensor_snapshot()
    finally:
        session.close()
    return (
        f"WH-station{number} snapshot ready; "
        f"cold source=WH-station1; cold={snapshot.cold_temp_f:.2f} F"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--water",
        action="store_true",
        help="also initialize the valve output LOW and require a scheduled draw",
    )
    parser.add_argument("--schedule", type=Path, default=DEFAULT_CANONICAL_SCHEDULE)
    parser.add_argument("--cta-binary", type=Path, default=DEFAULT_CTA_BINARY)
    parser.add_argument("--serial-port", type=Path, default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--sensor-configuration", type=Path)
    parser.add_argument(
        "--disable-outside-communication-heartbeat",
        action="store_true",
        help="report that recurring outside-communication refreshes are disabled",
    )
    parser.add_argument(
        "--power-configuration-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "saved_data" / "calibration",
    )
    return parser


def run_preflight(args: argparse.Namespace) -> list[PreflightCheck]:
    checks = [
        _check("platform", _require_linux),
        _check("Python smbus2", lambda: _require_module("smbus2")),
        _check("CTA controller", lambda: _require_executable(args.cta_binary)),
        _check("CTA serial port", lambda: _require_device_access(args.serial_port)),
        _check(
            "I2C bus",
            lambda: _require_device_access(
                Path(f"/dev/i2c-{MAX1238_I2C_BUS}")
            ),
        ),
        _check(
            "results directory",
            lambda: _require_results_write(
                station_results_directory(args.results_root)
            ),
        ),
        _check(
            "schedule",
            lambda: _schedule_details(args.schedule, args.water),
        ),
        PreflightCheck(
            "outside communication heartbeat",
            True,
            (
                "disabled; 15-second command prerequisites remain enabled"
                if args.disable_outside_communication_heartbeat
                else "enabled; refresh interval 13 minutes 30 seconds"
            ),
        ),
        _check(
            "sensor configuration",
            lambda: _sensor_configuration_details(args.sensor_configuration),
        ),
        _check(
            "power configuration",
            lambda: _power_configuration_details(args.power_configuration_dir),
        ),
        _check(
            "MAX1238",
            lambda: _i2c_device_details(MAX1238_I2C_BUS, MAX1238_I2C_ADDR),
        ),
        _check(
            "ACS37800",
            lambda: _i2c_device_details(MAX1238_I2C_BUS, ACS37800_I2C_ADDR),
        ),
    ]
    if args.water:
        checks.extend(
            [
                _check("Python RPi.GPIO", lambda: _require_module("RPi.GPIO")),
                _check(
                    "station sensor snapshot",
                    lambda: _station_sensor_details(
                        args.sensor_configuration
                    ),
                ),
                _check("valve safety", _gpio_low_details),
            ]
        )
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = run_preflight(args)
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"PREFLIGHT_{status} {check.name}: {check.details}")
    failures = sum(not check.passed for check in checks)
    print(
        f"PREFLIGHT_SUMMARY passed={len(checks) - failures} "
        f"failed={failures} water={str(args.water).lower()}"
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
