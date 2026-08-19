#!/usr/bin/env python3
"""Create a per-phase EnergyTake, power, and state-verification summary."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from matplotlib.figure import Figure

from .run_plot import Sample, _without_startup_spikes, load_run_plot_data
from .state_verification_plot import ExpectedPhase, StateReport, load_verification_data


PLOT_FILENAME = "phase_summary.png"


@dataclass(frozen=True)
class PhaseSummary:
    phase: str
    duration_seconds: float
    start_energy_kwh: float
    end_energy_kwh: float
    change_energy_kwh: float
    minimum_energy_kwh: float
    maximum_energy_kwh: float
    average_power_kw: float | None
    maximum_power_kw: float | None
    energized_percent: float | None
    state_result: str


def _nearest(samples: tuple[Sample, ...], timestamp: datetime) -> Sample:
    return min(samples, key=lambda sample: abs((sample.timestamp - timestamp).total_seconds()))


def _power_statistics(
    samples: tuple[Sample, ...],
    start: datetime,
    end: datetime,
    *,
    energized_threshold_w: float,
) -> tuple[float | None, float | None, float | None]:
    if not samples or end <= start:
        return None, None, None
    active_index = 0
    for index, sample in enumerate(samples):
        if sample.timestamp <= start:
            active_index = index
        else:
            break
    if samples[active_index].timestamp > end:
        return None, None, None

    weighted_power = 0.0
    energized_seconds = 0.0
    covered_seconds = 0.0
    maximum = 0.0
    for index in range(active_index, len(samples)):
        sample = samples[index]
        interval_start = max(start, sample.timestamp)
        next_timestamp = samples[index + 1].timestamp if index + 1 < len(samples) else end
        interval_end = min(end, next_timestamp)
        if interval_end > interval_start:
            seconds = (interval_end - interval_start).total_seconds()
            weighted_power += sample.value * seconds
            covered_seconds += seconds
            if sample.value >= energized_threshold_w:
                energized_seconds += seconds
            maximum = max(maximum, sample.value)
        if next_timestamp >= end:
            break
    if covered_seconds <= 0:
        return None, None, None
    return (
        weighted_power / covered_seconds / 1000.0,
        maximum / 1000.0,
        energized_seconds / covered_seconds * 100.0,
    )


def _state_result(
    phase: ExpectedPhase,
    end: datetime,
    reports: tuple[StateReport, ...],
    *,
    grace_seconds: float,
    inclusive_end: bool = False,
) -> str:
    relevant = tuple(
        report
        for report in reports
        if phase.timestamp <= report.timestamp
        and (report.timestamp <= end if inclusive_end else report.timestamp < end)
    )
    if not relevant:
        return "No data"
    grace_end = phase.timestamp + timedelta(seconds=grace_seconds)
    after_grace = tuple(report for report in relevant if report.timestamp > grace_end)
    if any(report.code not in phase.expected_states for report in after_grace):
        return "Fail"
    if any(report.code in phase.expected_states for report in relevant):
        return "Pass"
    return "No data"


def summarize_run_phases(
    run_directory: Path | str,
    *,
    grace_seconds: float = 60,
    energized_threshold_w: float = 50,
) -> tuple[PhaseSummary, ...]:
    """Calculate report-ready metrics for each acknowledged scheduled phase."""
    if grace_seconds < 0:
        raise ValueError("grace_seconds cannot be negative")
    if energized_threshold_w < 0:
        raise ValueError("energized_threshold_w cannot be negative")
    plot_data = load_run_plot_data(run_directory)
    verification = load_verification_data(run_directory)
    power = _without_startup_spikes(plot_data.power)
    run_end = max(
        plot_data.energy[-1].timestamp,
        plot_data.power[-1].timestamp,
        verification.reports[-1].timestamp,
    )

    totals = Counter(phase.name for phase in verification.phases)
    seen: dict[str, int] = defaultdict(int)
    result: list[PhaseSummary] = []
    for index, phase in enumerate(verification.phases):
        end = verification.phases[index + 1].timestamp if index + 1 < len(verification.phases) else run_end
        if end <= phase.timestamp:
            continue
        seen[phase.name] += 1
        name = f"{phase.name} {seen[phase.name]}" if totals[phase.name] > 1 else phase.name
        start_sample = _nearest(plot_data.energy, phase.timestamp)
        end_sample = _nearest(plot_data.energy, end)
        within = tuple(sample for sample in plot_data.energy if phase.timestamp <= sample.timestamp <= end)
        energy_values = [sample.value for sample in within] or [start_sample.value, end_sample.value]
        average_kw, maximum_kw, energized_percent = _power_statistics(
            power,
            phase.timestamp,
            end,
            energized_threshold_w=energized_threshold_w,
        )
        result.append(
            PhaseSummary(
                phase=name,
                duration_seconds=(end - phase.timestamp).total_seconds(),
                start_energy_kwh=start_sample.value / 1000.0,
                end_energy_kwh=end_sample.value / 1000.0,
                change_energy_kwh=(end_sample.value - start_sample.value) / 1000.0,
                minimum_energy_kwh=min(energy_values) / 1000.0,
                maximum_energy_kwh=max(energy_values) / 1000.0,
                average_power_kw=average_kw,
                maximum_power_kw=maximum_kw,
                energized_percent=energized_percent,
                state_result=_state_result(
                    phase,
                    end,
                    verification.reports,
                    grace_seconds=grace_seconds,
                    inclusive_end=index + 1 == len(verification.phases),
                ),
            )
        )
    return tuple(result)


def _duration(seconds: float) -> str:
    total_minutes = round(seconds / 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


def _optional(value: float | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.2f}{suffix}"


def plot_phase_summary(
    run_directory: Path | str,
    *,
    grace_seconds: float = 60,
    energized_threshold_w: float = 50,
    output_path: Path | str | None = None,
    show: bool = False,
) -> tuple[Figure, Path | None]:
    """Create and optionally save/display a phase-summary figure."""
    directory = Path(run_directory).resolve()
    summaries = summarize_run_phases(
        directory,
        grace_seconds=grace_seconds,
        energized_threshold_w=energized_threshold_w,
    )
    if not summaries:
        raise ValueError("no phase summaries could be calculated")

    if show:
        import matplotlib.pyplot as plt

        figure = plt.figure(figsize=(13, 6.5))
    else:
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        figure = Figure(figsize=(13, 6.5))
        FigureCanvasAgg(figure)
    grid = figure.add_gridspec(2, 1, height_ratios=(1.1, 1.5), hspace=0.28)
    bar_axis = figure.add_subplot(grid[0])
    table_axis = figure.add_subplot(grid[1])

    changes = [summary.change_energy_kwh for summary in summaries]
    positions = list(range(len(summaries)))
    colors = ["#62ad62" if value >= 0 else "#df8a58" for value in changes]
    bars = bar_axis.barh(positions, changes, color=colors, edgecolor="#555555", linewidth=0.7)
    bar_axis.axvline(0, color="#333333", linewidth=1)
    bar_axis.set_yticks(positions, [summary.phase for summary in summaries])
    bar_axis.invert_yaxis()
    bar_axis.set_xlabel("Net EnergyTake Change (kWh)")
    bar_axis.grid(axis="x", alpha=0.3)
    margin = max(max(abs(value) for value in changes) * 0.03, 0.03)
    for bar, value in zip(bars, changes):
        bar_axis.text(
            value + (margin if value >= 0 else -margin),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.2f}",
            ha="left" if value >= 0 else "right",
            va="center",
            fontsize=9,
            fontweight="bold",
        )

    columns = ["Phase", "Duration", "Start\n(kWh)", "End\n(kWh)", "Change\n(kWh)", "Min\n(kWh)", "Max\n(kWh)", "Avg Power\n(kW)", "Max Power\n(kW)", "Energized", "State"]
    rows = [
        [
            item.phase,
            _duration(item.duration_seconds),
            f"{item.start_energy_kwh:.2f}",
            f"{item.end_energy_kwh:.2f}",
            f"{item.change_energy_kwh:+.2f}",
            f"{item.minimum_energy_kwh:.2f}",
            f"{item.maximum_energy_kwh:.2f}",
            _optional(item.average_power_kw),
            _optional(item.maximum_power_kw),
            _optional(item.energized_percent, "%"),
            item.state_result,
        ]
        for item in summaries
    ]
    table_axis.axis("off")
    table = table_axis.table(cellText=rows, colLabels=columns, cellLoc="center", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.65)
    for column in range(len(columns)):
        table[(0, column)].set_facecolor("#d9e3f0")
        table[(0, column)].set_text_props(fontweight="bold")
    state_column = len(columns) - 1
    state_colors = {"Pass": "#a8d5a8", "Fail": "#efaaaa", "No data": "#dddddd"}
    for row_index, item in enumerate(summaries, start=1):
        table[(row_index, state_column)].set_facecolor(state_colors[item.state_result])
        table[(row_index, state_column)].set_text_props(fontweight="bold")

    figure.suptitle(f"{directory.name}\nPhase Summary", fontsize=14, y=0.98)
    figure.text(
        0.99,
        0.015,
        f"EnergyTake boundaries use nearest samples. Power is time-weighted; energized ≥ {energized_threshold_w:g} W. State grace: {grace_seconds:g} s.",
        ha="right",
        va="bottom",
        fontsize=7,
        color="#555555",
    )
    figure.subplots_adjust(left=0.1, right=0.97, bottom=0.08, top=0.86)

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
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--grace-seconds", type=float, default=60)
    parser.add_argument("--energized-threshold-w", type=float, default=50)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    try:
        output = args.output or args.run_directory / PLOT_FILENAME
        _, destination = plot_phase_summary(
            args.run_directory,
            grace_seconds=args.grace_seconds,
            energized_threshold_w=args.energized_threshold_w,
            output_path=output,
            show=args.show,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"PHASE_SUMMARY_ERROR {type(exc).__name__}: {exc}\n")
    print(f"PHASE_SUMMARY {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
