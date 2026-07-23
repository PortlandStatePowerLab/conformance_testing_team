"""Command-line entrypoint for the grouped sensor diagnostic."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from software.sensors import sensor_diagnostic as diagnostic
from software.adc.max1238_builder import build_max1238
from software.sensors.sensor_diagnostic import DEFAULT_WATCH_INTERVAL_S, run_sensor_check
from software.sensors.sensor_reader import SensorReader, SensorSnapshot

time = diagnostic.time


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read one sensor snapshot or watch continuously.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-s", type=float, default=DEFAULT_WATCH_INTERVAL_S)
    args = parser.parse_args(argv)
    if args.interval_s <= 0.0:
        parser.error("--interval-s must be greater than zero")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    adc = build_max1238()
    try:
        run_sensor_check(SensorReader(adc), watch=args.watch, interval_s=args.interval_s)
    except KeyboardInterrupt:
        print("Sensor check stopped.")
    finally:
        adc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
