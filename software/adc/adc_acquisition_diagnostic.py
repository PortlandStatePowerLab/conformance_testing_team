#!/usr/bin/env python3
"""Compare MAX1238 grouped and single acquisition behavior safely.

This diagnostic performs only MAX1238 I2C reads. It does not configure GPIO,
actuate the valve, or access the ACS37800. Only one hardware-owning process
should run at a time.
"""

# region Imports

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Protocol
from software.station.station_hardware_map import CH_AMBIENT, CH_COLD, CH_FLOW, CH_HOT

# endregion Imports

# region Diagnostic Configuration

ADC_REFERENCE_VOLTAGE_V = 4.096
ADC_COUNT_RANGE = 4096
DEFAULT_SAMPLES = 20
DEFAULT_DELAY_S = 0.10
DEFAULT_CLOCK_MODE = "internal"
SEQUENCE_NAMES = ("A", "B", "C")

# Explicitly retain every station channel constant used by the grouped scan map.
STATION_CHANNELS = (CH_HOT, CH_COLD, CH_FLOW, CH_AMBIENT)

# endregion Diagnostic Configuration

# region Interfaces and Results


class DiagnosticAdc(Protocol):
    """Define the MAX1238 operations and ownership used by this diagnostic."""

    def read_single(self, channel: int, /) -> int | None:
        """Read one channel and return its ADC counts."""
        ...

    def read_range(self, first_channel: int, last_channel: int, /) -> dict[int, int]:
        """Read an inclusive channel range keyed by channel number."""
        ...

    def setup_adc(self, **kwargs: object) -> None:
        """Transmit an explicit MAX1238 setup configuration."""
        ...

    def close(self) -> None:
        """Close the owned ADC connection."""
        ...


@dataclass(frozen=True)
class AcquisitionResult:
    """Store one acquisition comparison with explicit count values."""

    sequence_name: str
    first_counts: int
    second_counts: int
    delta_counts: int
    elapsed_s: float


@dataclass
class SequenceStats:
    """Accumulate both readings and deltas for one sequence."""

    first_values_counts: list[int] = field(default_factory=list)
    second_values_counts: list[int] = field(default_factory=list)
    deltas_counts: list[int] = field(default_factory=list)

    def update(self, result: AcquisitionResult) -> None:
        """Add both readings and the defined delta from one result."""
        self.first_values_counts.append(result.first_counts)
        self.second_values_counts.append(result.second_counts)
        self.deltas_counts.append(result.delta_counts)

# endregion Interfaces and Results

# region Acquisition and Reporting


def counts_to_voltage(raw_counts: int) -> float:
    """Convert ADC counts to approximate volts using 4.096 V / 4096 counts."""
    return raw_counts * ADC_REFERENCE_VOLTAGE_V / ADC_COUNT_RANGE


def require_counts(raw_counts: int | None, *, reading_name: str) -> int:
    """Return valid ADC counts or raise when a single read returned no value."""
    if raw_counts is None:
        raise RuntimeError(f"ADC returned no value for {reading_name}")
    return raw_counts


def acquire_sequence(
    adc: DiagnosticAdc,
    sequence_name: str,
    *,
    start_monotonic_s: float,
) -> AcquisitionResult:
    """Perform one read-only MAX1238 acquisition sequence on the injected ADC.

    This function performs only MAX1238 I2C reads. It does not configure GPIO,
    actuate the valve, or access the ACS37800. Only one hardware-owning process
    should run at a time.
    """
    if sequence_name == "A":
        grouped = adc.read_range(CH_HOT, CH_AMBIENT)
        grouped_flow_counts = grouped[CH_FLOW]
        single_flow_counts = require_counts(
            adc.read_single(CH_FLOW), reading_name="single CH_FLOW"
        )
        first_counts = grouped_flow_counts
        second_counts = single_flow_counts
    elif sequence_name == "B":
        single_flow_counts = require_counts(
            adc.read_single(CH_FLOW), reading_name="single CH_FLOW"
        )
        grouped = adc.read_range(CH_HOT, CH_AMBIENT)
        grouped_flow_counts = grouped[CH_FLOW]
        first_counts = grouped_flow_counts
        second_counts = single_flow_counts
    elif sequence_name == "C":
        first_single_counts = require_counts(
            adc.read_single(CH_FLOW), reading_name="first single CH_FLOW"
        )
        second_single_counts = require_counts(
            adc.read_single(CH_FLOW), reading_name="second single CH_FLOW"
        )
        first_counts = first_single_counts
        second_counts = second_single_counts
    else:
        raise ValueError(f"Unknown acquisition sequence: {sequence_name}")

    return AcquisitionResult(
        sequence_name=sequence_name,
        first_counts=first_counts,
        second_counts=second_counts,
        delta_counts=second_counts - first_counts,
        elapsed_s=max(0.0, time.monotonic() - start_monotonic_s),
    )


def print_sample(result: AcquisitionResult) -> None:
    """Print one comparison sample with counts, voltages, delta, and runtime."""
    if result.sequence_name in ("A", "B"):
        print(
            f"sequence={result.sequence_name} "
            f"grouped_flow_counts={result.first_counts} "
            f"grouped_flow_voltage_v={counts_to_voltage(result.first_counts):.4f} "
            f"single_flow_counts={result.second_counts} "
            f"flow_voltage_v={counts_to_voltage(result.second_counts):.4f} "
            f"delta_counts={result.delta_counts} "
            f"elapsed_s={result.elapsed_s:.3f}"
        )
    else:
        print(
            f"sequence=C first_single_counts={result.first_counts} "
            f"first_flow_voltage_v={counts_to_voltage(result.first_counts):.4f} "
            f"second_single_counts={result.second_counts} "
            f"flow_voltage_v={counts_to_voltage(result.second_counts):.4f} "
            f"delta_counts={result.delta_counts} "
            f"elapsed_s={result.elapsed_s:.3f}"
        )


def print_summaries(stats_by_sequence: dict[str, SequenceStats]) -> None:
    """Print cumulative count and delta statistics for every sequence."""
    print("Acquisition summaries")
    for sequence_name in SEQUENCE_NAMES:
        stats = stats_by_sequence[sequence_name]
        if not stats.first_values_counts:
            print(f"  Sequence {sequence_name}: sample_count=0")
            continue
        first_label, second_label = (
            ("grouped", "single")
            if sequence_name in ("A", "B")
            else ("first_single", "second_single")
        )
        print(
            f"  Sequence {sequence_name}: sample_count={len(stats.first_values_counts)} "
            f"{first_label}_minimum_counts={min(stats.first_values_counts)} "
            f"{first_label}_maximum_counts={max(stats.first_values_counts)} "
            f"{first_label}_mean_counts={statistics.fmean(stats.first_values_counts):.2f} "
            f"{second_label}_minimum_counts={min(stats.second_values_counts)} "
            f"{second_label}_maximum_counts={max(stats.second_values_counts)} "
            f"{second_label}_mean_counts={statistics.fmean(stats.second_values_counts):.2f} "
            f"delta_minimum_counts={min(stats.deltas_counts)} "
            f"delta_maximum_counts={max(stats.deltas_counts)} "
            f"delta_mean_counts={statistics.fmean(stats.deltas_counts):.2f}"
        )


def run_comparison(
    adc: DiagnosticAdc,
    *,
    samples: int,
    delay_s: float,
    watch: bool,
) -> None:
    """Run read-only MAX1238 comparisons with one injected ADC object.

    This function performs only MAX1238 I2C reads. It does not configure GPIO,
    actuate the valve, or access the ACS37800. Only one hardware-owning process
    should run at a time. Watch mode prints a cumulative summary after every
    batch of ``samples`` comparisons.
    """
    stats_by_sequence = {name: SequenceStats() for name in SEQUENCE_NAMES}
    start_monotonic_s = time.monotonic()
    sample_index = 0

    while True:
        for _ in range(samples):
            sequence_name = SEQUENCE_NAMES[sample_index % len(SEQUENCE_NAMES)]
            result = acquire_sequence(
                adc,
                sequence_name,
                start_monotonic_s=start_monotonic_s,
            )
            stats_by_sequence[sequence_name].update(result)
            print_sample(result)
            sample_index += 1
            if delay_s > 0.0:
                time.sleep(delay_s)

        print_summaries(stats_by_sequence)
        if not watch:
            return
        print()

# endregion Acquisition and Reporting
