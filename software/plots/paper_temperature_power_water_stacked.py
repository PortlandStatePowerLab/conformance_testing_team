"""Paper temperature, power and water panels with command and Op State bands."""

import argparse
from datetime import time
from pathlib import Path

from software.plots.paper_run_plot_water import plot_paper_run
from software.plots.paper_style import save_paper


def plot_paper_temperature_power_water_stacked(
    run_directory, *, width=3.5, height=5.5, scenario_start=None,
    include_isolated_state5=False,
):
    return plot_paper_run(
        run_directory, width=width, height=height, scenario_start=scenario_start,
        include_isolated_state5=include_isolated_state5, primary="temperature",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--height", type=float, default=5.5)
    parser.add_argument("--start", type=time.fromisoformat)
    parser.add_argument("--include-isolated-state5", action="store_true")
    args = parser.parse_args()
    figure = plot_paper_temperature_power_water_stacked(
        args.run_directory, width=args.width, height=args.height,
        scenario_start=args.start, include_isolated_state5=args.include_isolated_state5,
    )
    for path in save_paper(
        figure, args.run_directory, "paper_temperature_power_water", args.output_directory
    ):
        print(path)


if __name__ == "__main__":
    main()
