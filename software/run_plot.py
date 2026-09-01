#!/usr/bin/env python3
"""Plot EnergyTake, real power, and attempted CTA phases for one test run."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterable

from matplotlib.figure import Figure

from .equipment_metadata import equipment_title_line
from .time_axis import apply_clock_ticks


PLOT_FILENAME = "energy_take_power.png"


@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    value: float
    record_reason: str = ""


@dataclass(frozen=True)
class Phase:
    timestamp: datetime
    name: str
    command: str = ""
    accepted: bool = True
    result: str = ""


@dataclass(frozen=True)
class RunPlotData:
    energy: tuple[Sample, ...]
    power: tuple[Sample, ...]
    phases: tuple[Phase, ...]
    energy_column: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"required plot source not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    # All source columns are explicitly Pacific time, but commodity rows omit
    # the numeric UTC offset while power/event rows include it.  Use one common
    # Pacific wall-clock representation so the streams remain comparable.
    return datetime.fromisoformat(normalized).replace(tzinfo=None)


def _samples(
    rows: Iterable[dict[str, str]], column: str, *, valid_status_only: bool = False
) -> tuple[Sample, ...]:
    result: list[Sample] = []
    for row in rows:
        if valid_status_only and row.get("status", "").strip().lower() != "ok":
            continue
        raw_value = row.get(column, "").strip()
        raw_timestamp = row.get("timestamp_pacific", "").strip()
        if not raw_value or not raw_timestamp:
            continue
        try:
            result.append(
                Sample(
                    _timestamp(raw_timestamp),
                    float(raw_value),
                    row.get("record_reason", "").strip().lower(),
                )
            )
        except ValueError:
            continue
    if not result:
        raise ValueError(f"no valid {column} samples found")
    return tuple(sorted(result, key=lambda sample: sample.timestamp))


def _phase_name(command: str) -> str | None:
    return {
        "advanced_load_up": "ALU",
        "load_up": "Load Up",
        "shed": "Shed",
        "critical_peak": "CP",
        "grid_emergency": "GE",
        "run_normal": "Normal",
    }.get(command.strip().lower())


def _command_phases(rows: Iterable[dict[str, str]]) -> tuple[Phase, ...]:
    """Return accepted implementations and terminally rejected command attempts."""
    phases: list[Phase] = []
    accepted_commands: set[str] = set()
    for row in rows:
        event = row.get("event", "").strip().lower()
        result = row.get("result", "").strip().lower()
        command = row.get("command", "").strip().lower()
        name = _phase_name(command)
        acknowledged = (
            event == "application_ack" and result == "ack"
        ) or (
            event == "intermediate_response" and result == "success"
        )
        rejected = event == "command_completed" and result not in {"", "ok", "success"}
        if name is None or not (acknowledged or rejected):
            continue
        if acknowledged:
            accepted_commands.add(command)
        phase = Phase(
            _timestamp(row["timestamp_pacific"]),
            name,
            command,
            acknowledged,
            "" if acknowledged else result,
        )
        if (
            phases
            and phases[-1].name == phase.name
            and phases[-1].accepted == phase.accepted
            and phases[-1].result == phase.result
        ):
            continue
        phases.append(phase)
    return tuple(sorted(phases, key=lambda phase: phase.timestamp))


def _acknowledged_phases(rows: Iterable[dict[str, str]]) -> tuple[Phase, ...]:
    """Backward-compatible accepted-only view used by older callers."""
    return tuple(phase for phase in _command_phases(rows) if phase.accepted)


def load_run_plot_data(run_directory: Path | str) -> RunPlotData:
    """Load and validate the three CSV sources used by the run plot."""
    directory = Path(run_directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(f"run directory not found: {directory}")

    event_rows = _read_csv(directory / "cta_events.csv")
    phases = _command_phases(event_rows)
    advanced = any(
        row.get("command", "").strip().lower() == "advanced_load_up"
        for row in event_rows
    )
    energy_column = (
        "advanced_present_energy_storage_Wh"
        if advanced
        else "present_energy_storage_Wh"
    )
    commodity_rows = _read_csv(directory / "cta_commodity.csv")
    try:
        energy = _samples(commodity_rows, energy_column)
    except ValueError:
        if energy_column != "advanced_present_energy_storage_Wh":
            raise
        # Older CEA-2045 devices can accept the test command but expose only
        # regular EnergyTake commodity data.
        energy_column = "present_energy_storage_Wh"
        energy = _samples(commodity_rows, energy_column)
    power = _samples(
        _read_csv(directory / "power.csv"), "real_power", valid_status_only=True
    )
    return RunPlotData(energy, power, phases, energy_column)


def _shift(timestamp: datetime, actual_start: datetime, display_start: datetime) -> datetime:
    return display_start + (timestamp - actual_start)


def _duck_curve_display_start(
    actual_start: datetime,
    phases,
    *,
    scenario_start: time | None = None,
    event_end: time = time(21, 10),
    fallback_start: time = time(15, 30),
) -> datetime:
    """Align the end of the final Shed/CP/GE block to the evening peak."""
    if scenario_start is not None:
        return datetime.combine(actual_start.date(), scenario_start)
    event_names = {"Shed", "CP", "GE"}
    boundary: datetime | None = None
    for index, phase in enumerate(phases[:-1]):
        if phase.name in event_names and phases[index + 1].name not in event_names:
            boundary = phases[index + 1].timestamp
    if boundary is None:
        return datetime.combine(actual_start.date(), fallback_start)
    desired_boundary = datetime.combine(actual_start.date(), event_end)
    return desired_boundary - (boundary - actual_start)


def _without_startup_spikes(samples: tuple[Sample, ...]) -> tuple[Sample, ...]:
    """Remove isolated, one-sample compressor inrush transients."""
    filtered: list[Sample] = []
    startup_armed_until: datetime | None = None
    for index, sample in enumerate(samples):
        reasons = set(sample.record_reason.split("|"))
        if "heater_off" in reasons:
            startup_armed_until = None
        if "heater_on" in reasons:
            startup_armed_until = sample.timestamp + timedelta(seconds=120)
        startup_armed = (
            startup_armed_until is not None
            and sample.timestamp <= startup_armed_until
        )
        if index + 1 >= len(samples):
            filtered.append(sample)
            continue
        following = samples[index + 1]
        delay = (following.timestamp - sample.timestamp).total_seconds()
        sharp_drop = sample.value > 0 and sample.value >= 3 * following.value
        is_startup_spike = (
            startup_armed
            and "power_change" in reasons
            and 0 < delay <= 2
            and sharp_drop
        )
        if is_startup_spike:
            startup_armed_until = None
            continue
        filtered.append(sample)
    return tuple(filtered)


def plot_run(
    run_directory: Path | str,
    *,
    scenario_start: time | None = None,
    output_path: Path | str | None = None,
    show: bool = False,
    suppress_startup_spikes: bool = True,
    energy_change_from_start: bool = False,
) -> tuple[Figure, Path | None]:
    """Create a third-example-style run plot and optionally save/display it."""
    directory = Path(run_directory).resolve()
    data = load_run_plot_data(directory)
    actual_start = min(data.energy[0].timestamp, data.power[0].timestamp)
    actual_end = max(data.energy[-1].timestamp, data.power[-1].timestamp)
    display_start = _duck_curve_display_start(
        actual_start, data.phases, scenario_start=scenario_start
    )

    energy_times = [_shift(x.timestamp, actual_start, display_start) for x in data.energy]
    plotted_power = (
        _without_startup_spikes(data.power) if suppress_startup_spikes else data.power
    )
    power_times = [_shift(x.timestamp, actual_start, display_start) for x in plotted_power]
    energy_baseline = data.energy[0].value if energy_change_from_start else 0.0
    energy_kwh = [(x.value - energy_baseline) / 1000.0 for x in data.energy]
    power_kw = [x.value / 1000.0 for x in plotted_power]

    if show:
        import matplotlib.pyplot as plt

        figure = plt.figure(figsize=(12, 6.75))
    else:
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        figure = Figure(figsize=(12, 6.75))
        FigureCanvasAgg(figure)
    grid = figure.add_gridspec(2, 1, height_ratios=(0.065, 1), hspace=0)
    phase_axis = figure.add_subplot(grid[0])
    energy_axis = figure.add_subplot(grid[1], sharex=phase_axis)
    power_axis = energy_axis.twinx()
    energy_label = "EnergyTake Change" if energy_change_from_start else "EnergyTake"
    energy_line, = energy_axis.plot(
        energy_times, energy_kwh, color="green", linewidth=1.6, label=energy_label
    )
    power_line, = power_axis.plot(
        power_times, power_kw, color="red", linewidth=1.15, label="Real Power"
    )
    power_axis.fill_between(power_times, power_kw, color="red", alpha=0.18)

    plot_end = _shift(actual_end, actual_start, display_start)
    shifted_phases = [
        Phase(
            _shift(phase.timestamp, actual_start, display_start),
            phase.name,
            phase.command,
            phase.accepted,
            phase.result,
        )
        for phase in data.phases
        if actual_start <= phase.timestamp <= actual_end
    ]
    # A startup command acknowledged within the first minute defines the opening phase.
    if shifted_phases and (shifted_phases[0].timestamp - display_start).total_seconds() <= 60:
        first = shifted_phases[0]
        shifted_phases[0] = Phase(
            display_start, first.name, first.command, first.accepted, first.result
        )

    phase_colors = {
        "ALU": "#cfe8cf",
        "Load Up": "#cfe8cf",
        "Shed": "#f8d58a",
        "CP": "#f8d58a",
        "GE": "#efaaaa",
        "Normal": "#dbe6ef",
    }
    for index, phase in enumerate(shifted_phases):
        phase_end = shifted_phases[index + 1].timestamp if index + 1 < len(shifted_phases) else plot_end
        if phase_end <= phase.timestamp:
            continue
        color = phase_colors.get(phase.name, "#eeeeee") if phase.accepted else "white"
        energy_axis.axvspan(
            phase.timestamp, phase_end, color=color, alpha=0.22, zorder=0
        )
        energy_axis.axvline(phase.timestamp, color="#666666", linewidth=0.8, alpha=0.65)
        phase_axis.axvspan(
            phase.timestamp,
            phase_end,
            facecolor=color,
            alpha=1.0,
        )
        phase_axis.axvline(phase.timestamp, color="#777777", linewidth=0.8)
        midpoint = phase.timestamp + (phase_end - phase.timestamp) / 2
        phase_axis.text(
            midpoint, 0.5,
            phase.name if phase.accepted else f"{phase.name}\nRejected: {phase.result}",
            ha="center", va="center", fontsize=10 if phase.accepted else 8,
            fontweight="bold", linespacing=0.9, clip_on=True,
        )
    if shifted_phases:
        phase_axis.axvline(plot_end, color="#777777", linewidth=0.8)

    energy_axis.set_xlim(display_start, plot_end)
    phase_axis.set_ylim(0, 1)
    phase_axis.set_yticks([])
    phase_axis.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
    for spine in phase_axis.spines.values():
        spine.set_color("#777777")
        spine.set_linewidth(0.8)
    if energy_change_from_start:
        energy_axis.axhline(0, color="#555555", linewidth=1.0, alpha=0.8)
    else:
        energy_axis.set_ylim(bottom=0)
    power_axis.set_ylim(bottom=0)
    energy_axis.set_xlabel("Duck-Curve Time")
    energy_axis.set_ylabel(
        "EnergyTake Change (kWh)" if energy_change_from_start else "EnergyTake (kWh)",
        color="green",
    )
    power_axis.set_ylabel("Real Power (kW)", color="red")
    energy_axis.tick_params(axis="y", colors="green")
    power_axis.tick_params(axis="y", colors="red")
    apply_clock_ticks(energy_axis, display_start, plot_end)
    energy_axis.grid(True, color="#b0b0b0", alpha=0.45)
    energy_axis.legend(handles=[energy_line, power_line], loc="upper left")
    equipment_line = equipment_title_line(directory)
    phase_axis.set_title(
        directory.name + (f"\n{equipment_line}" if equipment_line else ""), pad=8
    )
    figure.autofmt_xdate(rotation=45, ha="right")
    figure.tight_layout()

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
    parser.add_argument(
        "--start",
        help="override automatic 9:10 PM event-end alignment with start time HH:MM",
    )
    parser.add_argument("--show", action="store_true")
    parser.add_argument(
        "--include-startup-spikes",
        action="store_true",
        help="plot raw compressor-start inrush samples",
    )
    args = parser.parse_args()
    try:
        start = time.fromisoformat(args.start) if args.start else None
        output = args.output or args.run_directory / PLOT_FILENAME
        _, destination = plot_run(
            args.run_directory,
            scenario_start=start,
            output_path=output,
            show=args.show,
            suppress_startup_spikes=not args.include_startup_spikes,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"RUN_PLOT_ERROR {type(exc).__name__}: {exc}\n")
    print(f"RUN_PLOT {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
