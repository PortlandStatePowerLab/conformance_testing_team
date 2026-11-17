"""Plot measured outlet temperature and flow in one panel per water draw."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from matplotlib.figure import Figure

OUTPUT_NAME = "water_draw_temperature.png"


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


@dataclass
class Draw:
    event_id: str
    start: datetime
    stop: datetime
    samples: list
    reason: str
    threshold: float | None
    kind: str


def load_draws(directory: Path) -> list[Draw]:
    draws = []
    for path in directory.glob("water_draw_*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        samples = []
        stop = None
        reason = "not recorded"
        for row in rows:
            try:
                timestamp = datetime.fromisoformat(row.get("timestamp_pacific", "")).replace(tzinfo=None)
            except ValueError:
                continue
            if row.get("stop_reason"):
                reason = row["stop_reason"]
            if row.get("valve_state") == "closed":
                stop = timestamp
                continue  # Closing rows repeat the last snapshot; they are not fresh samples.
            temp, flow = finite(row.get("hot_temp_f")), finite(row.get("flow_gpm"))
            if temp is not None or flow is not None:
                samples.append((timestamp, temp, flow))
        if not samples or not any(flow is not None and flow > 0 for _, _, flow in samples):
            continue
        if not any(temp is not None for _, temp, _ in samples):
            continue
        samples.sort(key=lambda sample: sample[0])
        start = samples[0][0]
        threshold = None
        kind = ""
        log = path.with_suffix(".log")
        if log.is_file():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                prefix, _, payload = line.partition(" ")
                if prefix not in {"WATER_DRAW_READY", "WATER_DRAW_VALVE_OPEN", "WATER_DRAW_STOPPED"}:
                    continue
                try:
                    record = json.loads(payload)
                    if prefix == "WATER_DRAW_READY":
                        threshold = finite(record.get("stop_temp_f"))
                        kind = str(record.get("draw_type", "")).replace("_", " ")
                    elif prefix == "WATER_DRAW_VALVE_OPEN":
                        start = datetime.fromisoformat(record["timestamp_pacific"]).replace(tzinfo=None)
                    else:
                        stop = datetime.fromisoformat(record["timestamp_pacific"]).replace(tzinfo=None)
                        reason = record.get("stop_reason") or reason
                except (ValueError, KeyError, TypeError):
                    continue
        event_id = next((row["event_id"] for row in rows if row.get("event_id")), path.stem)
        draws.append(Draw(event_id, start, stop or samples[-1][0], samples, reason, threshold, kind))
    events = directory / "orchestrator_events.csv"
    if events.is_file():
        with events.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("event") != "water_draw_completed":
                    continue
                try:
                    details = json.loads(row.get("details") or "{}")
                except ValueError:
                    continue
                if details.get("reason") == "cut_in_observed":
                    for draw in draws:
                        if draw.event_id == row.get("event_id"):
                            draw.reason = "cut_in_observed"
    return sorted(draws, key=lambda draw: draw.start)


def build_figure(directory: Path) -> Figure:
    from software.plots.generate_temperature_power_water_plot import TEMPERATURE_COLOR
    from software.plots.run_plot import _command_phases
    from software.plots.run_plot_water import WATER_COLOR, STATUS_COLORS
    from software.plots.state_verification_plot import load_verification_data, verification_status
    from software.station.equipment_metadata import equipment_title_line

    draws = load_draws(directory)
    if not draws:
        raise ValueError("no water draws with recorded flow and temperature")
    event_file = directory / "cta_events.csv"
    if event_file.is_file():
        with event_file.open(encoding="utf-8-sig", newline="") as handle:
            phases = _command_phases(list(csv.DictReader(handle)))
    else:
        phases = ()
    try:
        verification = load_verification_data(directory)
    except (ValueError, FileNotFoundError):
        verification = None
    phase_colors = {"ALU": "#cfe8cf", "Load Up": "#cfe8cf", "Shed": "#f8d58a",
                    "CP": "#f8d58a", "GE": "#efaaaa", "Normal": "#dbe6ef"}
    temperatures = [temp for draw in draws for _, temp, _ in draw.samples if temp is not None]
    temperatures += [draw.threshold for draw in draws if draw.threshold is not None]
    minimum, maximum = min(temperatures), max(temperatures)
    margin = max(2, (maximum - minimum) * .08)
    max_flow = max(flow for draw in draws for _, _, flow in draw.samples if flow is not None)
    figure = Figure(figsize=(13.5, 5 * len(draws) + .8))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    FigureCanvasAgg(figure)
    equipment = equipment_title_line(directory)
    figure.suptitle(directory.name + (f"\n{equipment}" if equipment else ""), fontsize=13, y=.985)
    outer = figure.add_gridspec(len(draws), 1, left=.10, right=.90, top=.90,
                               bottom=.07, hspace=.32)
    for index, draw in enumerate(draws):
        grid = outer[index].subgridspec(3, 1, height_ratios=(.08, 1, .18), hspace=.025)
        command_axis = figure.add_subplot(grid[0])
        axis = figure.add_subplot(grid[1], sharex=command_axis)
        flow_axis = axis.twinx()
        state_axis = figure.add_subplot(grid[2], sharex=axis)
        elapsed = lambda timestamp: (timestamp - draw.start).total_seconds() / 60
        duration = max(0, elapsed(draw.stop))
        left, right = 0, max(duration, .01)
        window_start = draw.start
        window_stop = draw.stop
        # Clip command segments to each window, carrying in the active command.
        for pos, phase in enumerate(phases):
            phase_end = phases[pos + 1].timestamp if pos + 1 < len(phases) else window_stop
            start, end = max(window_start, phase.timestamp), min(window_stop, phase_end)
            if end <= start:
                continue
            color = phase_colors.get(phase.name, "#eeeeee") if phase.accepted else "white"
            axis.axvspan(elapsed(start), elapsed(end), color=color, alpha=.22, zorder=0)
            command_axis.axvspan(elapsed(start), elapsed(end), color=color)
            command_axis.text((elapsed(start) + elapsed(end)) / 2, .5,
                              phase.name if phase.accepted else f"{phase.name} rejected",
                              ha="center", va="center", fontsize=10, fontweight="bold", clip_on=True)
        if not phases:
            command_axis.text(.5, .5, "No recorded CTA command", transform=command_axis.transAxes,
                              ha="center", va="center", fontsize=9)
        command_axis.set_ylim(0, 1)
        command_axis.set_yticks([])
        command_axis.tick_params(axis="x", bottom=False, labelbottom=False)
        command_axis.set_title(f"{draw.event_id}" + (f" ({draw.kind})" if draw.kind else "")
                               + f" | Stop at {duration:.2f} min: {draw.reason.replace('_', ' ')}",
                               fontsize=10, loc="left", pad=8)
        minutes = [elapsed(timestamp) for timestamp, _, _ in draw.samples]
        temperature, = axis.plot(minutes, [temp if temp is not None else math.nan for _, temp, _ in draw.samples],
                                 color=TEMPERATURE_COLOR, label="Hot Water Temperature", linewidth=1.35, zorder=5)
        flow, = flow_axis.plot(minutes, [value if value is not None else math.nan for _, _, value in draw.samples],
                               color=WATER_COLOR, label="Water Draw", linewidth=1.1, alpha=.62)
        flow_axis.fill_between(minutes, [value if value is not None else math.nan for _, _, value in draw.samples],
                               color=WATER_COLOR, alpha=.09)
        handles = [temperature, flow]
        if draw.threshold is not None:
            handles.append(axis.axhline(draw.threshold, color="#b64632", linestyle="--", linewidth=.9,
                                       label=f"Stop threshold: {draw.threshold:g} °F"))
        for x, label in ((0, "Draw start"), (duration, "Draw stop")):
            axis.axvline(x, color="#555555", linestyle="--", linewidth=.8)
            axis.text(x, .02, label, transform=axis.get_xaxis_transform(), rotation=90,
                      va="bottom", ha="right", fontsize=8, color="#444444")
        axis.set_ylabel("Hot Water Temperature (°F)", color=TEMPERATURE_COLOR)
        axis.tick_params(axis="y", colors=TEMPERATURE_COLOR)
        flow_axis.set_ylabel("Water Flow (GPM)", color=WATER_COLOR)
        flow_axis.tick_params(axis="y", colors=WATER_COLOR)
        axis.set_ylim(minimum - margin, maximum + max(10, (maximum - minimum) * .20))
        flow_axis.set_ylim(0, max(4.5, max_flow * 1.2))
        axis.set_xlim(left, right)
        axis.tick_params(axis="x", bottom=False, labelbottom=False)
        axis.grid(color="#b0b0b0", alpha=.45)
        axis.legend(handles=handles, loc="upper center", ncol=len(handles), fontsize=8)
        reports = verification.reports if verification is not None else ()
        segments = []
        for pos, report in enumerate(reports):
            end = reports[pos + 1].timestamp if pos + 1 < len(reports) else window_stop
            start, end = max(window_start, report.timestamp), min(window_stop, end)
            if verification.verification_end is not None:
                end = min(end, verification.verification_end)
            if end <= start:
                continue
            status = verification_status(report, verification.phases)
            key = (report.name, status)
            if segments and segments[-1][2] == key:
                segments[-1][1] = end
            else:
                segments.append([start, end, key])
        state_axis.set_facecolor("#eeeeee")
        for start, end, (name, status) in segments:
            x1, x2 = elapsed(start), elapsed(end)
            state_axis.axvspan(x1, x2, color=STATUS_COLORS[status])
            state_axis.axvline(x1, color="#777777", linewidth=.65)
            if (x2 - x1) / (right - left) >= .035:
                state_axis.text((x1 + x2) / 2, .5, "\n".join(name.split()), ha="center", va="center",
                                fontsize=7.5, linespacing=.9, clip_on=True)
        if not segments:
            state_axis.text(.5, .5, "No reported operational state", transform=state_axis.transAxes,
                            ha="center", va="center", fontsize=8)
        state_axis.set_ylim(0, 1)
        state_axis.set_yticks([])
        state_axis.set_ylabel("Operational\nState", rotation=0, ha="right", va="center", labelpad=10)
        state_axis.set_xlabel("Minutes since valve opened")
        for band in (command_axis, state_axis):
            for spine in band.spines.values():
                spine.set_color("#777777")
                spine.set_linewidth(.8)
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
