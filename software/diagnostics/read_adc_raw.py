#!/usr/bin/env python3
"""Read and report MAX1238 ADC channels from the current WH1 channel map.

This diagnostic constructs and configures the station ADC, reads each mapped
sensor channel, and reports both the raw count and canonically converted input
voltage. In watch mode it also reports elapsed runtime and per-channel raw-count
ranges. It does not drive station outputs.
"""

# region Imports

# Enables postponed evaluation of type annotations as a Python language feature.
from __future__ import annotations

# Standard-library helpers for command-line parsing, timing, timestamps, and root discovery.
import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

# Makes the project package importable when this diagnostic runs as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Concrete station ADC construction and setup from ``max1238_builder.py``.
from software.adc.max1238_builder import build_max1238

# Shared hardware-agnostic ADC read interface from ``adc_interfaces.py``.
from software.adc.adc_interfaces import SensorAdc

# ADC configuration and channel assignments from ``hardware_map.py``.
from software.common.hardware_map import (
    ADC_PART,
    CH_AMBIENT,
    CH_COLD,
    CH_FLOW,
    CH_FUTURE,
    CH_HOT,
    MAX1238_I2C_ADDR,
    MAX1238_I2C_BUS,
)

# Nominal ADC configuration and canonical conversion from ``sensor_conversion.py``.
from software.sensor_conversion import (
    NOMINAL_SENSOR_CONFIG,
    adc_counts_to_voltage,
)

# endregion Imports

# region Diagnostic Configuration

CHANNELS = (
    ("hot_temp_transmitter", CH_HOT),
    ("cold_temp_transmitter", CH_COLD),
    ("flow_transmitter", CH_FLOW),
    ("future_input", CH_FUTURE),
    ("ambient_lm35", CH_AMBIENT),
)

DEFAULT_WATCH_INTERVAL_S = 1.0

# endregion Diagnostic Configuration

# region Diagnostic Reporting

# Tracks cumulative watch-mode runtime and per-channel raw-count ranges.
@dataclass
class AdcRawWatchStats:
    """Track cumulative read-adc-raw watch statistics."""

    start_monotonic_s: float
    scan_count: int = 0
    min_raw_counts_by_channel: dict[int, int] = field(default_factory=dict)
    max_raw_counts_by_channel: dict[int, int] = field(default_factory=dict)

    # Updates cumulative raw-count statistics with one complete ADC scan.
    def update(
        self,
        channel_readings: Sequence[tuple[str, int, int, float]],
    ) -> None:
        """Update watch statistics from one complete ADC channel scan."""
        self.scan_count += 1

        for _label, channel, raw_counts, _voltage_v in channel_readings:
            if channel not in self.min_raw_counts_by_channel:
                self.min_raw_counts_by_channel[channel] = raw_counts
            else:
                self.min_raw_counts_by_channel[channel] = min(
                    self.min_raw_counts_by_channel[channel],
                    raw_counts,
                )

            if channel not in self.max_raw_counts_by_channel:
                self.max_raw_counts_by_channel[channel] = raw_counts
            else:
                self.max_raw_counts_by_channel[channel] = max(
                    self.max_raw_counts_by_channel[channel],
                    raw_counts,
                )

    # Calculates elapsed watch runtime from ``now_monotonic_s``.
    def elapsed_s(self, now_monotonic_s: float) -> float:
        """Return elapsed watch runtime in seconds."""
        return max(0.0, now_monotonic_s - self.start_monotonic_s)


# Formats and prints one ADC raw diagnostic report.
def print_adc_raw_report(
    *,
    timestamp: datetime,
    adc_part: str,
    bus: int,
    address: int,
    reference_voltage_v: float,
    channel_readings: Sequence[tuple[str, int, int, float]],
) -> None:
    """Print one timestamped ADC raw report with explicit names and units."""
    timestamp_text = timestamp.astimezone().isoformat(timespec="seconds")

    print(
        f"ADC raw diagnostic at {timestamp_text}\n"
        "\n"
        "ADC configuration\n"
        f"  {'adc_part':<22}: {adc_part}\n"
        f"  {'i2c_bus':<22}: {bus}\n"
        f"  {'i2c_address':<22}: 0x{address:02X}\n"
        f"  {'reference_voltage_v':<22}: {reference_voltage_v:.3f} V\n"
        "\n"
        "Channel readings"
    )

    for label, channel, raw_counts, voltage_v in channel_readings:
        print(
            f"  CH{channel} {label}\n"
            f"    {'raw_counts':<18}: {raw_counts} counts\n"
            f"    {'input_voltage_v':<18}: {voltage_v:.4f} V"
        )


# Formats and prints cumulative watch-mode ADC raw statistics.
def print_adc_raw_watch_stats(
    stats: AdcRawWatchStats,
    *,
    channel_readings: Sequence[tuple[str, int, int, float]],
    now_monotonic_s: float,
) -> None:
    """Print elapsed runtime and per-channel raw-count limits."""
    print(
        "ADC raw watch runtime\n"
        f"  {'elapsed_s':<22}: {stats.elapsed_s(now_monotonic_s):.1f} s\n"
        f"  {'scans':<22}: {stats.scan_count}\n"
        "\n"
        "Raw count ranges"
    )

    for label, channel, _raw_counts, _voltage_v in channel_readings:
        print(
            f"  CH{channel} {label}\n"
            f"    {'min_raw_counts':<18}: "
            f"{stats.min_raw_counts_by_channel[channel]} counts\n"
            f"    {'max_raw_counts':<18}: "
            f"{stats.max_raw_counts_by_channel[channel]} counts"
        )

# endregion Diagnostic Reporting

# region ADC Scan Operations

# Reads all configured ADC channels once and returns raw counts with voltages.
def read_adc_channel_readings(
    adc: SensorAdc,
) -> list[tuple[str, int, int, float]]:
    """Read configured ADC channels and convert each raw count to voltage."""
    channel_readings: list[tuple[str, int, int, float]] = []

    for label, channel in CHANNELS:
        raw_counts = adc.read_single(channel)

        if raw_counts is None:
            raise RuntimeError(f"ADC returned no value for channel {channel}")

        voltage_v = adc_counts_to_voltage(raw_counts)
        channel_readings.append((label, channel, raw_counts, voltage_v))

    return channel_readings


# Runs one ADC raw report or watches continuously at ``interval_s``.
def run_adc_raw_check(
    adc: SensorAdc,
    *,
    bus: int,
    address: int,
    watch: bool,
    interval_s: float,
) -> None:
    """Collect and print raw ADC reports through an injected ADC."""
    watch_stats = AdcRawWatchStats(time.monotonic()) if watch else None

    while True:
        channel_readings = read_adc_channel_readings(adc)
        print_adc_raw_report(
            timestamp=datetime.now().astimezone(),
            adc_part=ADC_PART,
            bus=bus,
            address=address,
            reference_voltage_v=NOMINAL_SENSOR_CONFIG.adc_reference_voltage_v,
            channel_readings=channel_readings,
        )

        if not watch:
            return

        assert watch_stats is not None
        watch_stats.update(channel_readings)
        print_adc_raw_watch_stats(
            watch_stats,
            channel_readings=channel_readings,
            now_monotonic_s=time.monotonic(),
        )
        print()
        time.sleep(interval_s)

# endregion ADC Scan Operations

# region Diagnostic Entry Point

# Parses diagnostic command-line options.
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse read-adc-raw command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Read raw MAX1238 channels without driving outputs."
    )
    parser.add_argument(
        "--bus",
        type=int,
        default=MAX1238_I2C_BUS,
        help=f"I2C bus number, default {MAX1238_I2C_BUS}",
    )
    parser.add_argument(
        "--address",
        type=lambda value: int(value, 0),
        default=MAX1238_I2C_ADDR,
        help=f"MAX1238 I2C address, default 0x{MAX1238_I2C_ADDR:02X}",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="read raw ADC channels continuously until Ctrl+C",
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=DEFAULT_WATCH_INTERVAL_S,
        help=(
            "seconds between raw ADC scans in watch mode, "
            f"default {DEFAULT_WATCH_INTERVAL_S}"
        ),
    )
    args = parser.parse_args(argv)

    if args.interval_s <= 0.0:
        parser.error("--interval-s must be greater than zero")

    return args

# Constructs the ADC and reports raw counts and converted voltages without
# driving station outputs.
def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    adc = build_max1238(
        bus_num=args.bus,
        address=args.address,
    )

    try:
        run_adc_raw_check(
            adc,
            bus=args.bus,
            address=args.address,
            watch=args.watch,
            interval_s=args.interval_s,
        )
    except KeyboardInterrupt:
        print("ADC raw watch stopped.")
    finally:
        adc.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# endregion Diagnostic Entry Point
