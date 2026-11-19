"""Connected water-draw close-ups with an explicitly broken Pacific clock axis."""

from __future__ import annotations

import argparse
import math
from datetime import timedelta
from pathlib import Path

from matplotlib.ticker import FixedLocator, FuncFormatter

from software.plots.water_draw_temperature import build_figure as panel_figure, load_draws

OUTPUT_NAME = "water_draw_temperature_broken_axis.png"


def build_figure(directory: Path):
    directory = Path(directory).resolve()
    draws = load_draws(directory)
    if len(draws) < 2:
        raise ValueError("a broken-axis plot requires at least two recorded draws")
    if any(previous.stop > following.start for previous, following in zip(draws, draws[1:])):
        raise ValueError("water-draw time windows overlap")
    figure = panel_figure(directory, side_by_side=True)
    durations = [max((draw.stop - draw.start).total_seconds(), .6) for draw in draws]
    total = sum(durations)
    left, right, gap = .065, .95, .012
    available = right - left - gap * (len(draws) - 1)
    handles = {}
    cursor = left
    for index, (draw, duration) in enumerate(zip(draws, durations)):
        command, temperature, flow, state = figure.axes[index * 4:index * 4 + 4]
        width = available * duration / total
        for axis in (command, temperature, flow, state):
            position = axis.get_position()
            axis.set_position([cursor, position.y0, width, position.height])
            if index > 0:
                axis.spines["left"].set_visible(False)
            if index < len(draws) - 1:
                axis.spines["right"].set_visible(False)
        if index > 0:
            temperature.set_ylabel("")
            temperature.tick_params(axis="y", left=False, labelleft=False)
            state.set_ylabel("")
        if index < len(draws) - 1:
            flow.set_ylabel("")
            flow.tick_params(axis="y", right=False, labelright=False)
        legend = temperature.get_legend()
        if legend is not None:
            for line in legend.legend_handles if hasattr(legend, "legend_handles") else legend.legendHandles:
                handles.setdefault(line.get_label(), line)
            legend.remove()
        state.set_xlabel("")
        # Locate ticks at real clock-minute boundaries, not elapsed-minute offsets.
        step = max(1, math.ceil(duration / 60 / 4))
        tick = draw.start.replace(second=0, microsecond=0) + timedelta(minutes=1)
        ticks = []
        while tick < draw.stop:
            ticks.append((tick - draw.start).total_seconds() / 60)
            tick += timedelta(minutes=step)
        state.xaxis.set_major_locator(FixedLocator(ticks))
        state.xaxis.set_major_formatter(FuncFormatter(
            lambda value, pos, start=draw.start: (start + timedelta(minutes=value)).strftime("%I:%M %p")))
        state.tick_params(axis="x", rotation=30)
        # Diagonal marks span both sides of every gap across each plot band.
        for axis in (command, temperature, state):
            edges = ([0] if index > 0 else []) + ([1] if index < len(draws) - 1 else [])
            for edge in edges:
                for height in (0, 1):
                    axis.plot([edge - .007, edge + .007], [height - .025, height + .025],
                              transform=axis.transAxes, clip_on=False, color="#555555", linewidth=1)
        if index < len(draws) - 1:
            omitted = (draws[index + 1].start - draw.stop).total_seconds() / 60
            figure.text(cursor + width + gap / 2, .06, f"{omitted:.1f} min omitted",
                        ha="center", va="top", fontsize=8)
        cursor += width + gap
    figure.legend(handles=list(handles.values()), loc="upper center", bbox_to_anchor=(.5, .91),
                  ncol=len(handles), fontsize=9, frameon=True)
    figure.text(.5, .015, "Pacific clock time | Diagonal breaks omit the intervals between water draws",
                ha="center", fontsize=10)
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
