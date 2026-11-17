"""Original temperature/power/water layout ending 30 minutes after the final draw."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates

from software.plots.generate_temperature_power_water_plot import build_figure as full_figure
from software.plots.run_plot import _duck_curve_display_start, _shift, load_run_plot_data
from software.plots.time_axis import apply_clock_ticks
from software.plots.water_draw_temperature import load_draws

OUTPUT_NAME = "temperature_power_water_trimmed.png"


def cutoff_timestamp(directory: Path) -> datetime:
    draws = load_draws(directory)
    if not draws:
        raise ValueError("no recorded water draws with stop times found")
    return max(draw.stop for draw in draws) + timedelta(minutes=30)


def _recenter_band_labels(axis, left: float, right: float) -> None:
    """Keep labels centered in the visible parts of existing shaded segments."""
    bounds = []
    for patch in axis.patches:
        extent = patch.get_extents().transformed(axis.transData.inverted())
        bounds.append((extent.xmin, extent.xmax))
    for label in axis.texts:
        x, y = label.get_position()
        number = mdates.date2num(x) if isinstance(x, datetime) else float(x)
        segment = next(((start, end) for start, end in bounds if start <= number <= end), None)
        if segment is None:
            label.set_visible(left <= number <= right)
            continue
        start, end = max(left, segment[0]), min(right, segment[1])
        label.set_visible(end > start)
        if end > start:
            label.set_position(((start + end) / 2, y))


def build_figure(directory: Path):
    directory = Path(directory).resolve()
    cutoff = cutoff_timestamp(directory)
    data = load_run_plot_data(directory)
    actual_start = min(data.energy[0].timestamp, data.power[0].timestamp)
    display_start = _duck_curve_display_start(actual_start, data.phases)
    figure = full_figure(directory)
    left, original_right = figure.axes[1].get_xlim()
    # Do not extend beyond the original plot if recording ended earlier.
    right = min(original_right, mdates.date2num(_shift(cutoff, actual_start, display_start)))
    if right <= left:
        figure.clear()
        raise ValueError("draw cutoff does not fall after the plot start")
    for axis in (figure.axes[0], figure.axes[-1]):
        _recenter_band_labels(axis, left, right)
    for axis in figure.axes:
        axis.set_xlim(left, right)
    apply_clock_ticks(figure.axes[-1], mdates.num2date(left).replace(tzinfo=None),
                      mdates.num2date(right).replace(tzinfo=None))
    return figure


def generate(directory: Path, output_path: Path | None = None) -> Path:
    directory = Path(directory).resolve()
    figure = build_figure(directory)
    destination = Path(output_path or directory / OUTPUT_NAME).resolve()
    try:
        figure.savefig(destination, dpi=160, bbox_inches="tight")
    finally:
        figure.clear()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(generate(args.run_directory, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
