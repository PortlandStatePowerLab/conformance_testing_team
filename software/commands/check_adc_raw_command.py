"""Command-line entrypoint for the read-only MAX1238 raw diagnostic."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from software.adc import adc_raw_diagnostic as diagnostic
from software.adc.adc_raw_diagnostic import (
    CHANNELS,
    DEFAULT_WATCH_INTERVAL_S,
    run_adc_raw_check,
)
from software.adc.max1238_builder import build_max1238
from software.station.station_hardware_map import MAX1238_I2C_ADDR, MAX1238_I2C_BUS

time = diagnostic.time


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read raw MAX1238 channels without outputs.")
    parser.add_argument("--bus", type=int, default=MAX1238_I2C_BUS)
    parser.add_argument("--address", type=lambda value: int(value, 0), default=MAX1238_I2C_ADDR)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-s", type=float, default=DEFAULT_WATCH_INTERVAL_S)
    args = parser.parse_args(argv)
    if args.interval_s <= 0.0:
        parser.error("--interval-s must be greater than zero")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    adc = build_max1238(bus_num=args.bus, address=args.address)
    try:
        run_adc_raw_check(adc, bus=args.bus, address=args.address, watch=args.watch, interval_s=args.interval_s)
    except KeyboardInterrupt:
        print("ADC raw watch stopped.")
    finally:
        adc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
