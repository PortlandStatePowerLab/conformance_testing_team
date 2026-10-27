"""Single-column reported EnergyTake change chart without the metrics table."""

import argparse
from pathlib import Path

from software.plots.paper_style import equipment_name, paper_figure, save_paper, style_axis
from software.plots.phase_summary_plot import summarize_run_phases
from matplotlib.ticker import MaxNLocator


def plot_paper_phase_summary(run_directory, *, width=3.5, height=2.6):
    summaries = summarize_run_phases(run_directory)
    if not summaries:
        raise ValueError("no phase summaries found")
    figure = paper_figure(width, height)
    axis = figure.subplots()
    values = [s.change_energy_kwh for s in summaries]
    axis.barh(range(len(values)), values,
              color=["#62ad62" if v >= 0 else "#df8a58" for v in values], linewidth=.5, edgecolor="0.3")
    axis.set_yticks(range(len(values)))
    axis.set_yticklabels([s.phase for s in summaries], fontsize=9)
    axis.invert_yaxis()
    axis.axvline(0, color="0.3", linewidth=.5)
    pad = max(max(abs(v) for v in values) * .05, .02)
    axis.set_xlim(min(0, min(values)) - 8 * pad, max(0, max(values)) + 8 * pad)
    for i, value in enumerate(values):
        axis.text(value + (pad if value >= 0 else -pad), i, f"{value:+.2f}",
                  ha="left" if value >= 0 else "right", va="center", fontsize=9)
    axis.set_xlabel("Reported Net EnergyTake\nChange (kWh)", fontsize=9)
    axis.set_title(equipment_name(run_directory), fontsize=10)
    style_axis(axis)
    axis.set_yticks(range(len(values)))
    axis.set_yticklabels([s.phase for s in summaries], fontsize=9)
    axis.xaxis.set_major_locator(MaxNLocator(nbins=3))
    axis.grid(False)
    axis.grid(axis="x", alpha=.2, linewidth=.4)
    figure.subplots_adjust(left=.28, right=.97, top=.86, bottom=.25)
    return figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--height", type=float, default=2.6)
    args = parser.parse_args()
    figure = plot_paper_phase_summary(args.run_directory, width=args.width, height=args.height)
    for path in save_paper(figure, args.run_directory, "paper_phase_summary", args.output_directory):
        print(path)


if __name__ == "__main__":
    main()
