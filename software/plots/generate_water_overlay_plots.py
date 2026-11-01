#!/usr/bin/env python3
"""Generate experimental EnergyTake/power plots with water flow overlays."""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import timedelta
from pathlib import Path

import matplotlib.dates as mdates


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from software.plots.measurement_time_range import measurement_end_timestamp
from software.plots.run_plot import (  # noqa: E402
    _duck_curve_display_start,
    _shift,
    _timestamp,
    load_run_plot_data,
    plot_run,
)
from software.plots.state_verification_plot import (  # noqa: E402
    load_verification_data,
    verification_status,
)


OUTPUT_NAME = "energy_take_power_water.png"
WATER_COLOR = "#1677b8"
FLOW_STARTUP_SECONDS = 8.0
STATUS_COLORS = {
    "Pass": "#9fd39f",
    "Grace": "#ffe29a",
    "Fail": "#ee9999",
    "No expectation": "#dddddd",
}


def load_water_flow(directory: Path):
    """Return flow samples with explicit zero-flow boundaries for every draw."""
    samples = []
    for path in sorted(directory.glob("water_draw_*.csv")):
        draw = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                raw_time = row.get("timestamp_pacific", "").strip()
                raw_flow = row.get("flow_gpm", "").strip()
                if not raw_time or not raw_flow:
                    continue
                try:
                    draw.append((_timestamp(raw_time), float(raw_flow)))
                except ValueError:
                    continue
        if not draw:
            continue
        draw.sort()
        # The flow sensor overshoots for a few seconds as the valve opens.
        # Replace only that startup window with the settled flow level so the
        # plot emphasizes the sustained draw rather than the hydraulic spike.
        started = draw[0][0]
        settled_values = [
            value
            for timestamp, value in draw
            if FLOW_STARTUP_SECONDS
            <= (timestamp - started).total_seconds()
            <= FLOW_STARTUP_SECONDS + 12.0
        ]
        if settled_values:
            settled_flow = statistics.median(settled_values)
            draw = [
                (timestamp, settled_flow)
                if (timestamp - started).total_seconds() < FLOW_STARTUP_SECONDS
                else (timestamp, value)
                for timestamp, value in draw
            ]
        samples.append((draw[0][0] - timedelta(seconds=1), 0.0))
        samples.extend(draw)
        samples.append((draw[-1][0] + timedelta(seconds=1), 0.0))
    return sorted(samples)


def add_operational_state_band(
    figure, directory: Path, actual_start, actual_end, display_start
):
    """Add a reported-state band colored by verification result."""
    verification = load_verification_data(directory)
    energy_axis = figure.axes[1]
    phase_axis = figure.axes[0]
    power_axis = figure.axes[2]
    water_axis = figure.axes[3]

    phase_position = phase_axis.get_position()
    main_position = energy_axis.get_position()
    band_height = 0.085
    band_gap = 0.012
    band_bottom = main_position.y0
    new_main_bottom = band_bottom + band_height + band_gap
    new_main_position = [
        main_position.x0,
        new_main_bottom,
        main_position.width,
        main_position.y1 - new_main_bottom,
    ]
    energy_axis.set_position(new_main_position)
    power_axis.set_position(new_main_position)
    water_axis.set_position(new_main_position)

    state_axis = figure.add_axes(
        [main_position.x0, band_bottom, main_position.width, band_height],
        sharex=energy_axis,
    )
    state_axis.set_zorder(5)

    reports = [
        report
        for report in verification.reports
        if actual_start <= report.timestamp <= actual_end
    ]
    is_wh4_comparison = directory.name.startswith("WH-4_")
    if not is_wh4_comparison:
        filtered_reports = []
        for index, report in enumerate(reports):
            previous = reports[index - 1] if index > 0 else None
            following = reports[index + 1] if index + 1 < len(reports) else None
            isolated_state_5 = (
                report.code == 5
                and previous is not None
                and following is not None
                and previous.code != 5
                and following.code != 5
                and (previous.code, previous.name) == (following.code, following.name)
            )
            if not isolated_state_5:
                filtered_reports.append(report)
        reports = filtered_reports
    segments = []
    for report in reports:
        status = verification_status(report, verification.phases)
        key = (report.name, status)
        if segments and segments[-1][2] == key:
            continue
        segments.append([max(report.timestamp, actual_start), actual_end, key])
        if len(segments) > 1:
            segments[-2][1] = report.timestamp

    total_seconds = max((actual_end - actual_start).total_seconds(), 1.0)
    for start, end, (name, status) in segments:
        shifted_start = _shift(start, actual_start, display_start)
        shifted_end = _shift(end, actual_start, display_start)
        state_axis.axvspan(shifted_start, shifted_end, color=STATUS_COLORS[status])
        state_axis.axvline(shifted_start, color="#777777", linewidth=0.65)
        fraction = (end - start).total_seconds() / total_seconds
        if fraction >= 0.035:
            midpoint = shifted_start + (shifted_end - shifted_start) / 2
            state_name = "\n".join(name.split())
            show_status = status != "Pass" or is_wh4_comparison
            label = (
                f"{state_name}\n{status}"
                if fraction >= 0.06 and show_status
                else state_name
            )
            state_axis.text(
                midpoint,
                0.5,
                label,
                ha="center",
                va="center",
                fontsize=7 if fraction < 0.06 else 7.5,
                fontweight="bold" if status in {"Pass", "Fail"} else "normal",
                linespacing=0.9,
                clip_on=True,
            )

    plot_end = _shift(actual_end, actual_start, display_start)
    state_axis.set_xlim(display_start, plot_end)
    state_axis.set_ylim(0, 1)
    state_axis.set_yticks([])
    state_axis.set_ylabel(
        "Operational\nState", rotation=0, ha="right", va="center", labelpad=10
    )
    state_axis.xaxis.set_major_locator(mdates.HourLocator())
    state_axis.xaxis.set_major_formatter(mdates.DateFormatter("%I:%M %p"))
    state_axis.tick_params(axis="x", rotation=45)
    state_axis.set_xlabel("Duck-Curve Time")
    for spine in state_axis.spines.values():
        spine.set_color("#777777")
        spine.set_linewidth(0.8)

    energy_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    energy_axis.set_xlabel("")
    # Keep the phase strip exactly aligned with the resized main panel.
    phase_axis.set_position(
        [new_main_position[0], phase_position.y0, new_main_position[2], phase_position.height]
    )
    return state_axis


def generate(directory: Path) -> Path:
    data = load_run_plot_data(directory)
    actual_start = min(data.energy[0].timestamp, data.power[0].timestamp)
    actual_end = measurement_end_timestamp(directory, data.energy[-1].timestamp, data.power[-1].timestamp)
    display_start = _duck_curve_display_start(actual_start, data.phases)
    water = load_water_flow(directory)
    if not water:
        raise ValueError(f"no valid water-draw samples found in {directory}")

    figure, _ = plot_run(directory)
    figure.set_size_inches(13.5, 6.75)
    energy_axis = figure.axes[1]
    water_axis = energy_axis.twinx()
    water_axis.spines["right"].set_position(("outward", 62))

    times = [_shift(timestamp, actual_start, display_start) for timestamp, _ in water]
    flow = [value for _, value in water]
    water_line, = water_axis.plot(
        times,
        flow,
        color=WATER_COLOR,
        linewidth=1.1,
        alpha=0.62,
        label="Water Draw",
        zorder=4,
    )
    water_axis.fill_between(times, flow, color=WATER_COLOR, alpha=0.09, zorder=3)
    water_axis.set_ylim(bottom=0)
    water_axis.set_ylabel("Water Flow (GPM)", color=WATER_COLOR)
    water_axis.tick_params(axis="y", colors=WATER_COLOR)

    handles, labels = energy_axis.get_legend_handles_labels()
    energy_axis.legend(handles + [water_line], labels + ["Water Draw"], loc="upper left")

    # Preserve readable margins for the offset water-flow scale.
    figure.subplots_adjust(left=0.09, right=0.845, bottom=0.19, top=0.86)
    add_operational_state_band(
        figure, directory, actual_start, actual_end, display_start
    )
    output = directory / OUTPUT_NAME
    figure.savefig(output, dpi=160, bbox_inches="tight")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directories", type=Path, nargs="+")
    directories = parser.parse_args().run_directories
    for directory in directories:
        output = generate(directory)
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
