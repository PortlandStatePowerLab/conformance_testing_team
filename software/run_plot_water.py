#!/usr/bin/env python3
"""Plot EnergyTake, real power, water flow, and operational state for one run."""

from __future__ import annotations

import argparse
import csv
import statistics
from datetime import time, timedelta
from pathlib import Path

import matplotlib.dates as mdates

from .run_plot import (
    _duck_curve_display_start,
    _shift,
    _timestamp,
    load_run_plot_data,
    plot_run,
)
from .state_verification_plot import load_verification_data, verification_status


PLOT_FILENAME = "energy_take_power_water.png"
WATER_COLOR = "#1677b8"
FLOW_STARTUP_SECONDS = 8.0
STATUS_COLORS = {
    "Pass": "#9fd39f",
    "Grace": "#ffe29a",
    "Fail": "#ee9999",
    "No expectation": "#dddddd",
}


def load_water_flow(directory: Path):
    """Return flow samples with zero-flow boundaries around every draw."""
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


def _is_wh4(directory: Path) -> bool:
    return directory.parent.name.upper().replace("_", "-") == "WH-4"


def _legend_entries(axis):
    """Read legend entries through the cross-version Axes API."""
    return axis.get_legend_handles_labels()


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
    is_wh4 = _is_wh4(directory)
    if not is_wh4:
        filtered = []
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
                filtered.append(report)
        reports = filtered

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
            show_status = status != "Pass" or is_wh4
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
    phase_axis.set_position(
        [new_main_position[0], phase_position.y0, new_main_position[2], phase_position.height]
    )
    return state_axis


def plot_run_with_water(
    run_directory: Path | str,
    *,
    scenario_start: time | None = None,
    output_path: Path | str | None = None,
    show: bool = False,
    suppress_startup_spikes: bool = True,
):
    """Create and optionally save the water-overlay run plot."""
    directory = Path(run_directory).resolve()
    data = load_run_plot_data(directory)
    actual_start = min(data.energy[0].timestamp, data.power[0].timestamp)
    actual_end = max(data.energy[-1].timestamp, data.power[-1].timestamp)
    display_start = scenario_start or _duck_curve_display_start(actual_start, data.phases)
    water = load_water_flow(directory)

    figure, _ = plot_run(
        directory,
        scenario_start=scenario_start,
        suppress_startup_spikes=suppress_startup_spikes,
    )
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
    if not water:
        water_axis.text(
            0.99,
            0.03,
            "No water-draw data",
            transform=water_axis.transAxes,
            ha="right",
            va="bottom",
            fontsize=8,
            color=WATER_COLOR,
        )

    # Use the long-standing Axes API rather than version-specific Legend
    # attributes (legend_handles is unavailable on older station Matplotlib).
    handles, labels = _legend_entries(energy_axis)
    energy_axis.legend(handles + [water_line], labels + ["Water Draw"], loc="upper left")
    figure.subplots_adjust(left=0.09, right=0.845, bottom=0.19, top=0.86)
    add_operational_state_band(
        figure, directory, actual_start, actual_end, display_start
    )

    destination = None
    if output_path is not None:
        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=160, bbox_inches="tight")
    if show:
        import matplotlib.pyplot as plt

        plt.show()
    return figure, destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", help="override automatic start time with HH:MM")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--include-startup-spikes", action="store_true")
    args = parser.parse_args()
    try:
        _, destination = plot_run_with_water(
            args.run_directory,
            scenario_start=time.fromisoformat(args.start) if args.start else None,
            output_path=args.output or args.run_directory / PLOT_FILENAME,
            show=args.show,
            suppress_startup_spikes=not args.include_startup_spikes,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"ENERGY_TAKE_WATER_PLOT_ERROR {type(exc).__name__}: {exc}\n")
    print(f"ENERGY_TAKE_WATER_PLOT {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
