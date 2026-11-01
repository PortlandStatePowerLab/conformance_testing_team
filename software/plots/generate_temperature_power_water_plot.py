#!/usr/bin/env python3
"""Generate an experimental hot-temperature, power, water, and state plot."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from software.plots.run_plot import _duck_curve_display_start, _shift, _timestamp, load_run_plot_data  # noqa: E402
from software.plots.run_plot_water import plot_run_with_water  # noqa: E402


OUTPUT_NAME = "temperature_power_water.png"
TEMPERATURE_COLOR = "#14833b"


def load_hot_temperature(directory: Path):
    """Return one temperature series per draw so gaps remain unconnected."""
    series = []
    for path in sorted(directory.glob("water_draw_*.csv")):
        samples = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                raw_time = row.get("timestamp_pacific", "").strip()
                raw_temperature = row.get("hot_temp_f", "").strip()
                if not raw_time or not raw_temperature:
                    continue
                try:
                    samples.append((_timestamp(raw_time), float(raw_temperature)))
                except ValueError:
                    continue
        if samples:
            series.append(sorted(samples))
    return series


def generate(directory: Path, output_path: Path | None = None) -> Path:
    directory = directory.resolve()
    data = load_run_plot_data(directory)
    actual_start = min(data.energy[0].timestamp, data.power[0].timestamp)
    display_start = _duck_curve_display_start(actual_start, data.phases)
    temperatures = load_hot_temperature(directory)
    if not temperatures:
        raise ValueError("no valid hot-water temperature samples found")

    figure, _ = plot_run_with_water(directory)
    energy_axis = figure.axes[1]
    power_axis = figure.axes[2]
    water_axis = figure.axes[3]

    # Hide the EnergyTake series supplied by the shared base layout.
    for line in energy_axis.lines:
        if line.get_label() in {"EnergyTake", "EnergyTake Change"}:
            line.set_visible(False)

    temperature_line = None
    for samples in temperatures:
        times = [
            _shift(timestamp, actual_start, display_start)
            for timestamp, _ in samples
        ]
        values = [value for _, value in samples]
        line, = energy_axis.plot(
            times,
            values,
            color=TEMPERATURE_COLOR,
            linewidth=1.35,
            label="Hot Water Temperature" if temperature_line is None else "_nolegend_",
            zorder=5,
        )
        if temperature_line is None:
            temperature_line = line

    all_temperatures = [value for samples in temperatures for _, value in samples]
    minimum = min(all_temperatures)
    maximum = max(all_temperatures)
    temperature_range = maximum - minimum
    lower_margin = max(temperature_range * 0.08, 2.0)
    upper_margin = max(temperature_range * 0.20, 10.0)
    energy_axis.set_ylim(minimum - lower_margin, maximum + upper_margin)
    energy_axis.set_ylabel("Hot Water Temperature (°F)", color=TEMPERATURE_COLOR)
    energy_axis.tick_params(axis="y", colors=TEMPERATURE_COLOR)

    power_line = power_axis.lines[0]
    water_line = water_axis.lines[0]
    power_maximum = max((value for line in power_axis.lines for value in line.get_ydata()), default=0.0)
    water_maximum = max((value for line in water_axis.lines for value in line.get_ydata()), default=0.0)
    power_axis.set_ylim(0, max(0.5, power_maximum * 1.2))
    water_axis.set_ylim(0, max(4.5, water_maximum * 1.2))
    energy_axis.legend(
        handles=[temperature_line, power_line, water_line],
        labels=["Hot Water Temperature", "Real Power", "Water Draw"],
        loc="upper center",
        ncol=3,
    )

    destination = (output_path or directory / OUTPUT_NAME).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=160, bbox_inches="tight")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        output = generate(args.run_directory, args.output)
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"TEMPERATURE_PLOT_ERROR {type(exc).__name__}: {exc}\n")
    print(f"TEMPERATURE_PLOT {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
