#!/usr/bin/env python3
"""Read and report grouped water-heater sensor snapshots.

This diagnostic reports snapshots from an injected ``SensorReader``. It reads
one snapshot by default or watches continuously when requested. It does not
construct hardware, parse a command line, configure GPIO, or actuate the valve.
"""

# region Imports

# Enables postponed evaluation of type annotations as a Python language feature.
from __future__ import annotations

# Standard-library helpers for command-line parsing, timing, and timestamps.
import time
from dataclasses import dataclass
from datetime import datetime

# Grouped sensor reads and canonical conversions from ``sensor_reader.py``.
from software.sensors.sensor_reader import SensorReader, SensorSnapshot

# endregion Imports

# region Diagnostic Configuration

DEFAULT_WATCH_INTERVAL_S = 1.0

# endregion Diagnostic Configuration

# region Snapshot Reporting

# Tracks cumulative watch-mode runtime and flow raw-count range.
@dataclass
class WatchRuntimeStats:
    """Track cumulative sensor-check watch statistics."""

    start_monotonic_s: float
    snapshot_count: int = 0
    min_flow_raw_counts: int | None = None
    max_flow_raw_counts: int | None = None

    # Updates cumulative flow-count statistics with one grouped ``snapshot``.
    def update(self, snapshot: SensorSnapshot) -> None:
        """Update watch statistics from one grouped sensor snapshot."""
        flow_raw_counts = snapshot.flow_raw_counts
        self.snapshot_count += 1

        if self.min_flow_raw_counts is None:
            self.min_flow_raw_counts = flow_raw_counts
        else:
            self.min_flow_raw_counts = min(
                self.min_flow_raw_counts,
                flow_raw_counts,
            )

        if self.max_flow_raw_counts is None:
            self.max_flow_raw_counts = flow_raw_counts
        else:
            self.max_flow_raw_counts = max(
                self.max_flow_raw_counts,
                flow_raw_counts,
            )

    # Calculates elapsed watch runtime from ``now_monotonic_s``.
    def elapsed_s(self, now_monotonic_s: float) -> float:
        """Return elapsed watch runtime in seconds."""
        return max(0.0, now_monotonic_s - self.start_monotonic_s)


# Formats and prints one grouped ``snapshot`` with its local ``timestamp``.
def print_sensor_snapshot(
    snapshot: SensorSnapshot,
    timestamp: datetime,
) -> None:
    """Print one timestamped sensor snapshot with explicit names and units."""
    timestamp_text = timestamp.astimezone().isoformat(timespec="seconds")

    print(
        f"Sensor snapshot at {timestamp_text}\n"
        "\n"
        "Raw ADC counts\n"
        f"  {'hot_raw_counts':<18}: {snapshot.hot_raw_counts} counts\n"
        f"  {'cold_raw_counts':<18}: {snapshot.cold_raw_counts} counts\n"
        f"  {'flow_raw_counts':<18}: {snapshot.flow_raw_counts} counts\n"
        f"  {'ambient_raw_counts':<18}: {snapshot.ambient_raw_counts} counts\n"
        "\n"
        "Converted values\n"
        "  Temperatures (degC)\n"
        f"    {'hot_temp_c':<18}: {snapshot.hot_temp_c:.3f} °C\n"
        f"    {'cold_temp_c':<18}: {snapshot.cold_temp_c:.3f} °C\n"
        f"    {'ambient_temp_c':<18}: {snapshot.ambient_temp_c:.3f} °C\n"
        "\n"
        "  Temperatures (degF)\n"
        f"    {'hot_temp_f':<18}: {snapshot.hot_temp_f:.3f} °F\n"
        f"    {'cold_temp_f':<18}: {snapshot.cold_temp_f:.3f} °F\n"
        f"    {'ambient_temp_f':<18}: {snapshot.ambient_temp_f:.3f} °F\n"
        "\n"
        "  Flow\n"
        f"    {'flow_gpm':<18}: {snapshot.flow_gpm:.3f} GPM"
    )


# Formats and prints cumulative watch-mode runtime statistics.
def print_watch_runtime_stats(
    stats: WatchRuntimeStats,
    *,
    now_monotonic_s: float,
) -> None:
    """Print elapsed watch runtime and cumulative flow raw-count limits."""
    print(
        "Watch runtime\n"
        f"  {'elapsed_s':<22}: {stats.elapsed_s(now_monotonic_s):.1f} s\n"
        f"  {'snapshots':<22}: {stats.snapshot_count}\n"
        f"  {'flow_raw_counts_min':<22}: "
        f"{stats.min_flow_raw_counts} counts\n"
        f"  {'flow_raw_counts_max':<22}: "
        f"{stats.max_flow_raw_counts} counts"
    )


# Obtains and prints one snapshot or watches at ``interval_s`` until interrupted.
def run_sensor_check(
    reader: SensorReader,
    *,
    watch: bool,
    interval_s: float,
) -> None:
    """Collect and print grouped snapshots through an injected sensor reader."""
    watch_stats = WatchRuntimeStats(time.monotonic()) if watch else None

    while True:
        sensor_snapshot = reader.get_sensor_snapshot()
        print_sensor_snapshot(sensor_snapshot, datetime.now().astimezone())

        if not watch:
            return

        assert watch_stats is not None
        watch_stats.update(sensor_snapshot)
        print_watch_runtime_stats(
            watch_stats,
            now_monotonic_s=time.monotonic(),
        )
        print()
        time.sleep(interval_s)

# endregion Snapshot Reporting
