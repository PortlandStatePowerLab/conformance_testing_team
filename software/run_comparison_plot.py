#!/usr/bin/env python3
"""Compare baseline-relative EnergyTake and real power across compatible runs."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import matplotlib.dates as mdates
from matplotlib.figure import Figure

from .phase_summary_plot import summarize_run_phases
from .run_plot import RunPlotData, _shift, _without_startup_spikes, load_run_plot_data
from .state_verification_plot import ExpectedPhase, load_verification_data


PLOT_FILENAME = "energy_take_comparison.png"


@dataclass(frozen=True)
class ComparisonRun:
    directory: Path
    label: str
    plot_data: RunPlotData
    phases: tuple[ExpectedPhase, ...]
    state_failure: bool


def _base_label(directory: Path) -> str:
    heater = directory.parent.name
    match = re.search(r"(\d{4})_(\d{2})_(\d{2})_(\d{6})", directory.name)
    if match:
        date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        return f"{heater} — {date}"
    return f"{heater} — {directory.name}"


def _comparison_runs(run_directories: tuple[Path | str, ...], grace_seconds: float) -> tuple[ComparisonRun, ...]:
    if len(run_directories) < 2:
        raise ValueError("at least two run directories are required")
    preliminary = []
    for value in run_directories:
        directory = Path(value).resolve()
        verification = load_verification_data(directory)
        summaries = summarize_run_phases(directory, grace_seconds=grace_seconds)
        preliminary.append(
            ComparisonRun(
                directory,
                _base_label(directory),
                load_run_plot_data(directory),
                verification.phases,
                any(summary.state_result == "Fail" for summary in summaries),
            )
        )
    counts = Counter(item.label for item in preliminary)
    result = []
    for item in preliminary:
        label = item.label
        if counts[label] > 1:
            match = re.search(r"_(\d{6})_(?:PDT|PST)$", item.directory.name)
            if match:
                raw = match.group(1)
                label += f" {raw[:2]}:{raw[2:4]}:{raw[4:]}"
        result.append(ComparisonRun(item.directory, label, item.plot_data, item.phases, item.state_failure))
    return tuple(result)


def _validate_compatible(runs: tuple[ComparisonRun, ...], tolerance_seconds: float) -> None:
    reference = runs[0]
    reference_names = tuple(phase.name for phase in reference.phases)
    reference_start = reference.phases[0].timestamp
    reference_offsets = tuple((phase.timestamp - reference_start).total_seconds() for phase in reference.phases)
    for run in runs[1:]:
        names = tuple(phase.name for phase in run.phases)
        if names != reference_names:
            raise ValueError(
                f"incompatible phase sequence in {run.directory.name}: {names}; expected {reference_names}"
            )
        start = run.phases[0].timestamp
        offsets = tuple((phase.timestamp - start).total_seconds() for phase in run.phases)
        for index, (actual, expected) in enumerate(zip(offsets, reference_offsets)):
            if abs(actual - expected) > tolerance_seconds:
                raise ValueError(
                    f"incompatible phase timing in {run.directory.name} at {names[index]}: "
                    f"offset differs by {abs(actual - expected):.1f} seconds"
                )


def plot_run_comparison(
    run_directories: tuple[Path | str, ...] | list[Path | str],
    *,
    scenario_start: time = time(15, 30),
    timing_tolerance_seconds: float = 120,
    grace_seconds: float = 60,
    output_path: Path | str | None = None,
    show: bool = False,
) -> tuple[Figure, Path | None]:
    """Plot compatible runs on acknowledged-command-aligned shared axes."""
    if timing_tolerance_seconds < 0:
        raise ValueError("timing_tolerance_seconds cannot be negative")
    runs = _comparison_runs(tuple(run_directories), grace_seconds)
    _validate_compatible(runs, timing_tolerance_seconds)
    display_start = datetime.combine(datetime(2000, 1, 1).date(), scenario_start)

    aligned_ends = []
    for run in runs:
        actual_end = max(run.plot_data.energy[-1].timestamp, run.plot_data.power[-1].timestamp)
        aligned_ends.append(_shift(actual_end, run.phases[0].timestamp, display_start))
    display_end = max(aligned_ends)

    if show:
        import matplotlib.pyplot as plt

        figure = plt.figure(figsize=(13, 8))
    else:
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        figure = Figure(figsize=(13, 8))
        FigureCanvasAgg(figure)
    grid = figure.add_gridspec(3, 1, height_ratios=(0.09, 1, 0.75), hspace=0.04)
    phase_axis = figure.add_subplot(grid[0])
    energy_axis = figure.add_subplot(grid[1], sharex=phase_axis)
    power_axis = figure.add_subplot(grid[2], sharex=phase_axis)

    colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]
    for index, run in enumerate(runs):
        color = colors[index % len(colors)]
        anchor = run.phases[0].timestamp
        energy_times = [_shift(sample.timestamp, anchor, display_start) for sample in run.plot_data.energy]
        baseline = run.plot_data.energy[0].value
        energy_values = [(sample.value - baseline) / 1000.0 for sample in run.plot_data.energy]
        power = _without_startup_spikes(run.plot_data.power)
        power_times = [_shift(sample.timestamp, anchor, display_start) for sample in power]
        power_values = [sample.value / 1000.0 for sample in power]
        label = run.label + (" (state failure)" if run.state_failure else "")
        style = "--" if run.state_failure else "-"
        energy_axis.plot(energy_times, energy_values, color=color, linestyle=style, linewidth=1.7, label=label)
        power_axis.plot(power_times, power_values, color=color, linestyle=style, linewidth=1.2, label=label)

    reference = runs[0]
    reference_anchor = reference.phases[0].timestamp
    shifted_phases = tuple(
        ExpectedPhase(_shift(phase.timestamp, reference_anchor, display_start), phase.name, phase.expected_states)
        for phase in reference.phases
    )
    phase_colors = {"ALU": "#cfe8cf", "Load Up": "#cfe8cf", "Shed": "#f8d58a", "CP": "#f8d58a", "GE": "#efaaaa", "Normal": "#dbe6ef"}
    for index, phase in enumerate(shifted_phases):
        end = shifted_phases[index + 1].timestamp if index + 1 < len(shifted_phases) else display_end
        phase_axis.axvspan(phase.timestamp, end, color=phase_colors.get(phase.name, "#eeeeee"))
        phase_axis.axvline(phase.timestamp, color="#666666", linewidth=0.8)
        midpoint = phase.timestamp + (end - phase.timestamp) / 2
        phase_axis.text(midpoint, 0.5, phase.name, ha="center", va="center", fontweight="bold", fontsize=9, clip_on=True)

    phase_axis.set_ylim(0, 1)
    phase_axis.set_yticks([])
    phase_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    energy_axis.axhline(0, color="#444444", linewidth=0.9)
    energy_axis.set_ylabel("EnergyTake Change (kWh)")
    energy_axis.grid(True, alpha=0.3)
    energy_axis.legend(loc="best", fontsize=8)
    energy_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    power_axis.set_ylim(bottom=0)
    power_axis.set_ylabel("Real Power (kW)")
    power_axis.set_xlabel("Duck-Curve Time (first acknowledged command aligned)")
    power_axis.grid(True, alpha=0.3)
    power_axis.xaxis.set_major_locator(mdates.HourLocator())
    power_axis.xaxis.set_major_formatter(mdates.DateFormatter("%I:%M %p"))
    power_axis.tick_params(axis="x", rotation=45)
    for axis in (phase_axis, energy_axis, power_axis):
        axis.set_xlim(display_start, display_end)
    figure.suptitle("EnergyTake and Real Power Comparison", fontsize=15, y=0.97)
    figure.subplots_adjust(left=0.09, right=0.98, bottom=0.12, top=0.9)

    destination: Path | None = None
    if output_path is not None:
        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=160, bbox_inches="tight")
    if show:
        plt.show()
    return figure, destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directories", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path(PLOT_FILENAME))
    parser.add_argument("--start", default="15:30", help="scenario command-anchor time in HH:MM")
    parser.add_argument("--timing-tolerance-seconds", type=float, default=120)
    parser.add_argument("--grace-seconds", type=float, default=60)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    try:
        _, destination = plot_run_comparison(
            args.run_directories,
            scenario_start=time.fromisoformat(args.start),
            timing_tolerance_seconds=args.timing_tolerance_seconds,
            grace_seconds=args.grace_seconds,
            output_path=args.output,
            show=args.show,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"RUN_COMPARISON_ERROR {type(exc).__name__}: {exc}\n")
    print(f"RUN_COMPARISON {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
