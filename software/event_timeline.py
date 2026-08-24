#!/usr/bin/env python3
"""Create command-relative CTA, power, commodity, and water-draw timelines."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from matplotlib.figure import Figure

from .equipment_metadata import equipment_title_line
from .run_plot import _read_csv, _timestamp, load_run_plot_data
from .state_verification_plot import load_verification_data


CSV_FILENAME = "event_timeline.csv"
PLOT_FILENAME = "event_timeline.png"


@dataclass(frozen=True)
class TimelineEvent:
    phase: str
    phase_start: datetime
    timestamp: datetime
    milestone: str
    observation: str
    source: str
    after_command_seconds: float = 0.0
    after_previous_seconds: float = 0.0


@dataclass(frozen=True)
class PowerPoint:
    timestamp: datetime
    current_a: float
    power_w: float
    mode: str


def _mode(current_a: float, previous: str = "standby") -> str:
    """Classify aggregate current with downward hysteresis."""
    if current_a > 19.0:
        return "combined"
    if previous == "combined" and current_a >= 18.5:
        return "combined"
    if current_a >= 16.0:
        return "element"
    if previous == "element" and current_a >= 15.5:
        return "element"
    if current_a >= 8.0:
        return "unexpected"
    if previous == "unexpected" and current_a >= 7.5:
        return "unexpected"
    if current_a >= 1.0:
        return "compressor"
    if previous == "compressor" and current_a >= 0.8:
        return "compressor"
    if current_a > 0.4:
        return "ramp"
    if previous == "ramp" and current_a >= 0.35:
        return "ramp"
    if current_a >= 0.2:
        return "fan"
    if previous == "fan" and current_a >= 0.15:
        return "fan"
    return "standby"


def _power_points(rows: list[dict[str, str]]) -> tuple[PowerPoint, ...]:
    points: list[PowerPoint] = []
    previous = "standby"
    for row in rows:
        if row.get("status", "").strip().lower() != "ok":
            continue
        try:
            timestamp = _timestamp(row["timestamp_pacific"])
            current = float(row["current_rms"])
            power = float(row["real_power"])
        except (KeyError, ValueError):
            continue
        mode = _mode(current, previous)
        points.append(PowerPoint(timestamp, current, power, mode))
        previous = mode

    # Suppress isolated startup/inrush classifications lasting two seconds or less.
    filtered = list(points)
    for index in range(1, len(points) - 1):
        prior, point, following = points[index - 1], points[index], points[index + 1]
        returns_to_prior = (
            point.mode != prior.mode
            and prior.mode == following.mode
            and (following.timestamp - point.timestamp).total_seconds() <= 2
        )
        startup_inrush = (
            point.mode in {"unexpected", "element", "combined"}
            and following.mode in {"fan", "ramp", "compressor"}
            and 0 < (following.timestamp - point.timestamp).total_seconds() <= 2
            and point.current_a >= 3 * max(following.current_a, 0.01)
        )
        if returns_to_prior:
            filtered[index] = replace(point, mode=prior.mode)
        elif startup_inrush:
            filtered[index] = replace(
                point,
                mode=following.mode,
                current_a=following.current_a,
                power_w=following.power_w,
            )
    return tuple(filtered)


def _power_milestone(previous: str, current: str) -> str:
    if current == "standby":
        return "Fan/load stopped"
    if current == "fan":
        return (
            "Compressor stopped; fan remains on"
            if previous in {"ramp", "compressor", "unexpected", "element", "combined"}
            else "Fan started"
        )
    if current == "ramp":
        return "Compressor ramping down" if previous == "compressor" else "Compressor ramp started"
    if current == "compressor":
        if previous in {"element", "combined"}:
            return "Resistance element stopped; compressor remains on"
        if previous == "unexpected":
            return "Unexpected load cleared; compressor remains on"
        return "Compressor started"
    return {
        "unexpected": "Unexpected intermediate load detected",
        "element": "Resistance element started",
        "combined": "Compressor and element operating",
    }[current]


def _phase_labels(phases) -> dict[datetime, str]:
    totals = Counter(phase.name for phase in phases)
    seen: dict[str, int] = defaultdict(int)
    labels: dict[datetime, str] = {}
    for phase in phases:
        seen[phase.name] += 1
        labels[phase.timestamp] = (
            f"{phase.name} {seen[phase.name]}" if totals[phase.name] > 1 else phase.name
        )
    return labels


def _active_phase(phases, timestamp: datetime):
    active = None
    for phase in phases:
        if phase.timestamp > timestamp:
            break
        active = phase
    return active


def _event(phase, label: str, timestamp: datetime, milestone: str, observation: str, source: str):
    return TimelineEvent(
        label,
        phase.timestamp,
        timestamp,
        milestone,
        observation,
        source,
        (timestamp - phase.timestamp).total_seconds(),
    )


def build_event_timeline(run_directory: Path | str) -> tuple[TimelineEvent, ...]:
    """Build a concise milestone sequence for one completed run."""
    directory = Path(run_directory).resolve()
    verification = load_verification_data(directory)
    plot_data = load_run_plot_data(directory)
    phases = verification.phases
    labels = _phase_labels(phases)
    run_end = max(
        verification.reports[-1].timestamp,
        plot_data.energy[-1].timestamp,
        plot_data.power[-1].timestamp,
    )
    events: list[TimelineEvent] = []

    for index, phase in enumerate(phases):
        label = labels[phase.timestamp]
        end = phases[index + 1].timestamp if index + 1 < len(phases) else run_end
        command_observation = "Accepted" if phase.accepted else f"Rejected: {phase.result}"
        events.append(_event(
            phase,
            label,
            phase.timestamp,
            "Command accepted" if phase.accepted else "Command rejected",
            command_observation,
            "CTA",
        ))
        if phase.accepted:
            expected = next(
                (
                    report
                    for report in verification.reports
                    if phase.timestamp <= report.timestamp < end
                    and report.code in phase.expected_states
                ),
                None,
            )
            expected_text = " or ".join(str(code) for code in sorted(phase.expected_states))
            if expected is not None:
                events.append(_event(
                    phase,
                    label,
                    expected.timestamp,
                    "Expected operational state first observed",
                    f"State {expected.code}: {expected.name} (expected {expected_text})",
                    "CTA state poll",
                ))
            else:
                events.append(_event(
                    phase,
                    label,
                    end,
                    "Expected operational state not observed",
                    f"Expected {expected_text}",
                    "CTA state poll",
                ))

            energy = tuple(
                sample for sample in plot_data.energy
                if phase.timestamp <= sample.timestamp < end
            )
            if energy:
                baseline = energy[0].value
                changed = next(
                    (sample for sample in energy[1:] if abs(sample.value - baseline) >= 30),
                    None,
                )
                if changed is not None:
                    events.append(_event(
                        phase,
                        label,
                        changed.timestamp,
                        "EnergyTake first changed",
                        f"{baseline:.0f} to {changed.value:.0f} Wh",
                        "Commodity poll",
                    ))

    points = _power_points(_read_csv(directory / "power.csv"))
    previous_mode = points[0].mode if points else "standby"
    for point in points[1:]:
        if point.mode == previous_mode:
            continue
        phase = _active_phase(phases, point.timestamp)
        if phase is not None:
            events.append(_event(
                phase,
                labels[phase.timestamp],
                point.timestamp,
                _power_milestone(previous_mode, point.mode),
                f"{point.current_a:.2f} A, {point.power_w:.0f} W (inferred)",
                "Power monitor",
            ))
        previous_mode = point.mode

    orchestrator_path = directory / "orchestrator_events.csv"
    if orchestrator_path.is_file():
        for row in _read_csv(orchestrator_path):
            kind = row.get("event", "").strip().lower()
            if kind not in {"water_draw_started", "water_draw_completed"}:
                continue
            try:
                timestamp = _timestamp(row["timestamp_pacific"])
                details = json.loads(row.get("details", "") or "{}")
            except (ValueError, json.JSONDecodeError):
                continue
            phase = _active_phase(phases, timestamp)
            if phase is None:
                continue
            event_id = row.get("event_id", "").strip() or "Water draw"
            if kind == "water_draw_started":
                observation = f"Target {float(details.get('target_volume_gal', 0)):.2f} gal"
                milestone = f"{event_id} started"
            else:
                draw_path = directory / f"{event_id}.csv"
                measured = None
                if draw_path.is_file():
                    draw_rows = _read_csv(draw_path)
                    if draw_rows:
                        try:
                            measured = float(draw_rows[-1]["accumulated_volume_gal"])
                        except (KeyError, ValueError):
                            pass
                observation = (
                    f"Measured {measured:.2f} gal" if measured is not None
                    else f"Return code {details.get('return_code', 'unknown')}"
                )
                milestone = f"{event_id} completed"
            events.append(_event(
                phase,
                labels[phase.timestamp],
                timestamp,
                milestone,
                observation,
                "Water draw",
            ))

    ordered = sorted(events, key=lambda item: (item.timestamp, item.source, item.milestone))
    previous_timestamp = ordered[0].timestamp if ordered else run_end
    result: list[TimelineEvent] = []
    for item in ordered:
        result.append(replace(
            item,
            after_previous_seconds=(item.timestamp - previous_timestamp).total_seconds(),
        ))
        previous_timestamp = item.timestamp
    return tuple(result)


def _duration(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    total = round(abs(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{sign}{hours}:{minutes:02d}:{secs:02d}" if hours else f"{sign}{minutes}:{secs:02d}"


def write_event_timeline_csv(events: tuple[TimelineEvent, ...], path: Path | str) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "phase", "timestamp_pacific", "time_after_command",
            "time_after_previous", "milestone", "observation", "source",
        ])
        for item in events:
            writer.writerow([
                item.phase,
                item.timestamp.isoformat(sep=" "),
                _duration(item.after_command_seconds),
                _duration(item.after_previous_seconds),
                item.milestone,
                item.observation,
                item.source,
            ])
    return destination


def plot_event_timeline(
    run_directory: Path | str,
    *,
    output_path: Path | str | None = None,
    csv_output_path: Path | str | None = None,
    show: bool = False,
) -> tuple[Figure, Path | None, Path | None]:
    directory = Path(run_directory).resolve()
    events = build_event_timeline(directory)
    if not events:
        raise ValueError("no timeline milestones found")
    csv_destination = write_event_timeline_csv(
        events, csv_output_path or directory / CSV_FILENAME
    )
    height = min(24.0, max(6.0, 1.8 + len(events) * 0.31))
    if show:
        import matplotlib.pyplot as plt
        figure = plt.figure(figsize=(16, height))
    else:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        figure = Figure(figsize=(16, height))
        FigureCanvasAgg(figure)
    axis = figure.add_subplot(111)
    axis.axis("off")
    rows = [[
        item.phase,
        _duration(item.after_command_seconds),
        _duration(item.after_previous_seconds),
        item.milestone,
        item.observation,
    ] for item in events]
    table = axis.table(
        cellText=rows,
        colLabels=["Phase", "After ACK", "After Previous", "Milestone", "Observation"],
        cellLoc="left",
        colLoc="center",
        colWidths=[0.11, 0.09, 0.10, 0.27, 0.43],
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.35)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("#777777")
        cell.set_linewidth(0.6)
        if row == 0:
            cell.set_facecolor("#dbe6ef")
            cell.set_text_props(weight="bold")
        elif rows[row - 1][3] == "Command rejected":
            cell.set_facecolor("#f4cccc")
        elif row % 2 == 0:
            cell.set_facecolor("#f5f5f5")
    equipment = equipment_title_line(directory)
    title = [directory.name]
    if equipment:
        title.append(equipment)
    title.append("Command-Relative Event Timeline")
    figure.suptitle("\n".join(title), fontsize=14, y=0.985)
    figure.text(
        0.5, 0.012,
        "Operational state and commodity milestones are first observed at polling time. Component operation is inferred from aggregate current and power.",
        ha="center", fontsize=8, color="#555555",
    )
    figure.subplots_adjust(left=0.02, right=0.98, top=0.90, bottom=0.05)
    destination = None
    if output_path is not None:
        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, dpi=160, bbox_inches="tight")
    if show:
        plt.show()
    return figure, destination, csv_destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    try:
        _, image_path, csv_path = plot_event_timeline(
            args.run_directory,
            output_path=args.output or args.run_directory / PLOT_FILENAME,
            csv_output_path=args.csv_output,
            show=args.show,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"EVENT_TIMELINE_ERROR {type(exc).__name__}: {exc}\n")
    print(f"EVENT_TIMELINE {image_path}")
    print(f"EVENT_TIMELINE_CSV {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
