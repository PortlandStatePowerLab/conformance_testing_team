"""Broken measurement axis with an unbroken, verified accepted-command header."""

from __future__ import annotations

import argparse
from pathlib import Path

from software.plots.run_plot import _command_phases, _read_csv
from software.plots.water_draw_temperature import load_draws
from software.plots.water_draw_temperature_broken_axis import build_figure as broken_figure

OUTPUT_NAME = "water_draw_temperature_continuous_command.png"


def continuous_command(directory: Path, start, end):
    phases = [phase for phase in _command_phases(_read_csv(directory / "cta_events.csv"))
              if phase.accepted and phase.timestamp <= end]
    active = [phase for phase in phases if phase.timestamp <= start]
    if not active:
        raise ValueError("no accepted command recorded before the first draw")
    first = active[-1]
    if any(phase.command != first.command for phase in phases if phase.timestamp > start):
        raise ValueError("accepted command changes between draws; a continuous single-command header would be misleading")
    return first


def build_figure(directory: Path):
    directory = Path(directory).resolve()
    draws = load_draws(directory)
    if len(draws) < 2:
        raise ValueError("this preview requires at least two recorded water draws")
    phase = continuous_command(directory, draws[0].start, draws[-1].stop)
    figure = broken_figure(directory)
    commands = [figure.axes[index * 4] for index in range(len(draws))]
    first, last = commands[0].get_position(), commands[-1].get_position()
    color = commands[0].patches[0].get_facecolor()
    for command in commands:
        position = command.get_position()
        figure.text(position.x0, position.y1 + .015, command.get_title(loc="left"),
                    fontsize=10, ha="left", va="bottom")
        command.set_visible(False)
    header = figure.add_axes([first.x0, first.y0, last.x1 - first.x0, first.height])
    header.set_facecolor(color)
    header.set_xticks([])
    header.set_yticks([])
    header.text(.5, .5, f"{phase.name} (accepted command unchanged across omitted interval)",
                transform=header.transAxes, ha="center", va="center", fontweight="bold", fontsize=10)
    for spine in header.spines.values():
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
