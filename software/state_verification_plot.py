#!/usr/bin/env python3
"""Plot commanded, expected, and reported CTA operational states for one run."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

import matplotlib.dates as mdates
from matplotlib.figure import Figure

from .run_plot import (
    _command_phases,
    _duck_curve_display_start,
    _phase_name,
    _read_csv,
    _shift,
    _timestamp,
)


PLOT_FILENAME = "operational_state_verification.png"


@dataclass(frozen=True)
class ExpectedPhase:
    timestamp: datetime
    name: str
    expected_states: frozenset[int]
    accepted: bool = True
    result: str = ""


@dataclass(frozen=True)
class StateReport:
    timestamp: datetime
    code: int
    name: str


@dataclass(frozen=True)
class VerificationData:
    phases: tuple[ExpectedPhase, ...]
    reports: tuple[StateReport, ...]


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y"}


def _expected_states(value: str) -> frozenset[int]:
    try:
        return frozenset(int(item.strip()) for item in value.split("|") if item.strip())
    except ValueError as exc:
        raise ValueError(f"invalid expected_operational_states: {value}") from exc


def _acknowledged(row: dict[str, str]) -> bool:
    event = row.get("event", "").strip().lower()
    result = row.get("result", "").strip().lower()
    return (event == "application_ack" and result == "ack") or (
        event == "intermediate_response" and result == "success"
    )


def load_verification_data(run_directory: Path | str) -> VerificationData:
    """Load scheduled expectations, acknowledged commands, and state reports."""
    directory = Path(run_directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(f"run directory not found: {directory}")

    scheduled: dict[str, deque[frozenset[int]]] = defaultdict(deque)
    for row in _read_csv(directory / "master_schedule.csv"):
        action = row.get("action", "").strip().lower()
        if not _enabled(row.get("enabled", "")) or _phase_name(action) is None:
            continue
        expected = _expected_states(row.get("expected_operational_states", ""))
        if not expected:
            raise ValueError(f"scheduled CTA action has no expected states: {action}")
        scheduled[action].append(expected)

    phases: list[ExpectedPhase] = []
    reports: list[StateReport] = []
    event_rows = _read_csv(directory / "cta_events.csv")
    for row in event_rows:
        command = row.get("command", "").strip().lower()
        if row.get("event", "").strip().lower() == "operational_state":
            raw_code = row.get("operational_state", "").strip()
            if raw_code:
                reports.append(
                    StateReport(
                        _timestamp(row["timestamp_pacific"]),
                        int(raw_code),
                        row.get("operational_state_name", "").strip() or f"State {raw_code}",
                    )
                )

    for phase in _command_phases(event_rows):
        if scheduled[phase.command]:
            phases.append(
                ExpectedPhase(
                    phase.timestamp,
                    phase.name,
                    scheduled[phase.command].popleft(),
                    phase.accepted,
                    phase.result,
                )
            )

    if not phases:
        raise ValueError("no acknowledged scheduled CTA phases found")
    if not reports:
        raise ValueError("no reported operational states found")
    return VerificationData(
        tuple(sorted(phases, key=lambda item: item.timestamp)),
        tuple(sorted(reports, key=lambda item: item.timestamp)),
    )


def _phase_at(phases: tuple[ExpectedPhase, ...], timestamp: datetime) -> ExpectedPhase | None:
    active: ExpectedPhase | None = None
    for phase in phases:
        if phase.timestamp > timestamp:
            break
        active = phase
    return active


def verification_status(
    report: StateReport,
    phases: tuple[ExpectedPhase, ...],
    *,
    grace_seconds: float = 60,
) -> str:
    phase = _phase_at(phases, report.timestamp)
    if phase is None:
        return "No expectation"
    if report.code in phase.expected_states:
        return "Pass" if phase.accepted else "Fail"
    if not phase.accepted:
        return "Fail"
    if (report.timestamp - phase.timestamp).total_seconds() <= grace_seconds:
        return "Grace"
    return "Fail"


def _segments(items, key, end: datetime):
    """Yield consecutive equal-key segments as (start, end, item)."""
    if not items:
        return
    start = items[0].timestamp
    current = items[0]
    for item in items[1:]:
        if key(item) != key(current):
            yield start, item.timestamp, current
            start = item.timestamp
            current = item
    yield start, end, current


def plot_state_verification(
    run_directory: Path | str,
    *,
    scenario_start: time | None = None,
    grace_seconds: float = 60,
    output_path: Path | str | None = None,
    show: bool = False,
) -> tuple[Figure, Path | None]:
    """Create and optionally save/display an operational-state verification plot."""
    if grace_seconds < 0:
        raise ValueError("grace_seconds cannot be negative")
    directory = Path(run_directory).resolve()
    data = load_verification_data(directory)
    actual_start = min(data.reports[0].timestamp, data.phases[0].timestamp)
    actual_end = max(data.reports[-1].timestamp, data.phases[-1].timestamp)
    display_start = _duck_curve_display_start(
        actual_start, data.phases, scenario_start=scenario_start
    )
    display_end = _shift(actual_end, actual_start, display_start)

    phases = tuple(
        ExpectedPhase(
            _shift(item.timestamp, actual_start, display_start),
            item.name,
            item.expected_states,
            item.accepted,
            item.result,
        )
        for item in data.phases
    )
    reports = tuple(
        StateReport(
            _shift(item.timestamp, actual_start, display_start), item.code, item.name
        )
        for item in data.reports
    )
    if (phases[0].timestamp - display_start).total_seconds() <= grace_seconds:
        first = phases[0]
        phases = (ExpectedPhase(
            display_start, first.name, first.expected_states, first.accepted, first.result
        ),) + phases[1:]

    if show:
        import matplotlib.pyplot as plt

        figure = plt.figure(figsize=(12, 5.5))
    else:
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        figure = Figure(figsize=(12, 5.5))
        FigureCanvasAgg(figure)
    grid = figure.add_gridspec(3, 1, height_ratios=(0.9, 1.25, 0.55), hspace=0.04)
    command_axis = figure.add_subplot(grid[0])
    report_axis = figure.add_subplot(grid[1], sharex=command_axis)
    result_axis = figure.add_subplot(grid[2], sharex=command_axis)

    phase_colors = {"ALU": "#cfe8cf", "Load Up": "#cfe8cf", "Shed": "#f8d58a", "CP": "#f8d58a", "GE": "#efaaaa", "Normal": "#dbe6ef"}
    total_seconds = max((display_end - display_start).total_seconds(), 1)
    for start, end, phase in _segments(
        phases,
        lambda item: (item.name, item.expected_states, item.accepted, item.result),
        display_end,
    ):
        command_axis.axvspan(
            start,
            end,
            facecolor=phase_colors.get(phase.name, "#eeeeee") if phase.accepted else "white",
        )
        command_axis.axvline(start, color="#666666", linewidth=0.8)
        codes = sorted(phase.expected_states)
        segment_fraction = (end - start).total_seconds() / total_seconds
        if segment_fraction < 0.06:
            expected = f"Exp.\n{'|'.join(str(code) for code in codes)}"
            phase_fontsize = 8
            expected_fontsize = 6.5
        elif segment_fraction < 0.11:
            expected = f"Expected:\n{' or '.join(str(code) for code in codes)}"
            phase_fontsize = 9
            expected_fontsize = 7
        else:
            expected = f"Expected: {' or '.join(str(code) for code in codes)}"
            phase_fontsize = 11
            expected_fontsize = 8
        midpoint = start + (end - start) / 2
        command_axis.text(
            midpoint, 0.6,
            phase.name if phase.accepted else f"{phase.name}\nRejected: {phase.result}",
            ha="center", va="center",
            fontweight="bold", fontsize=phase_fontsize, clip_on=True
        )
        command_axis.text(
            midpoint, 0.23, expected, ha="center", va="center",
            fontsize=expected_fontsize, linespacing=0.9, clip_on=True
        )

    state_colors = {0: "#dbe6ef", 1: "#cfe8cf", 2: "#f8d58a", 3: "#b7ddb7", 4: "#efc875", 5: "#dddddd", 6: "#9dcc9d"}
    for start, end, report in _segments(reports, lambda item: (item.code, item.name), display_end):
        report_axis.axvspan(start, end, color=state_colors.get(report.code, "#dddddd"))
        report_axis.axvline(start, color="#777777", linewidth=0.6)
        if (end - start).total_seconds() >= 8 * 60:
            midpoint = start + (end - start) / 2
            segment_fraction = (end - start).total_seconds() / total_seconds
            if segment_fraction < 0.06:
                state_label = f"{report.code}\n" + "\n".join(report.name.split())
                state_fontsize = 6.5
            elif segment_fraction < 0.11:
                state_label = f"{report.code}\n" + "\n".join(report.name.split())
                state_fontsize = 7.5
            else:
                state_label = f"{report.code}\n{report.name}"
                state_fontsize = 9
            report_axis.text(
                midpoint, 0.5, state_label, ha="center", va="center",
                fontsize=state_fontsize, linespacing=0.9, clip_on=True
            )

    statuses = tuple(
        StateReport(
            report.timestamp,
            report.code,
            verification_status(report, phases, grace_seconds=grace_seconds),
        )
        for report in reports
    )
    status_colors = {"Pass": "#9fd39f", "Grace": "#ffe29a", "Fail": "#ee9999", "No expectation": "#dddddd"}
    for start, end, item in _segments(statuses, lambda value: value.name, display_end):
        result_axis.axvspan(start, end, color=status_colors[item.name])
        if (end - start).total_seconds() >= 8 * 60:
            midpoint = start + (end - start) / 2
            result_axis.text(midpoint, 0.5, item.name, ha="center", va="center", fontweight="bold", fontsize=9)

    for axis, label in ((command_axis, "Command"), (report_axis, "Reported"), (result_axis, "Verification")):
        axis.set_ylim(0, 1)
        axis.set_yticks([])
        axis.set_ylabel(label, rotation=0, ha="right", va="center", labelpad=12)
        axis.set_xlim(display_start, display_end)
        for spine in axis.spines.values():
            spine.set_color("#666666")
            spine.set_linewidth(0.8)
    command_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    report_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    result_axis.xaxis.set_major_locator(mdates.HourLocator())
    result_axis.xaxis.set_major_formatter(mdates.DateFormatter("%I:%M %p"))
    result_axis.set_xlabel("Duck-Curve Time")
    result_axis.tick_params(axis="x", rotation=45)
    command_axis.set_title(f"{directory.name}\nOperational-State Verification", pad=10)
    figure.subplots_adjust(left=0.12, right=0.98, bottom=0.18, top=0.82, hspace=0.04)

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
    parser.add_argument("--grace-seconds", type=float, default=60)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    try:
        output = args.output or args.run_directory / PLOT_FILENAME
        _, destination = plot_state_verification(
            args.run_directory,
            scenario_start=time.fromisoformat(args.start) if args.start else None,
            grace_seconds=args.grace_seconds,
            output_path=output,
            show=args.show,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"STATE_VERIFICATION_PLOT_ERROR {type(exc).__name__}: {exc}\n")
    print(f"STATE_VERIFICATION_PLOT {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
