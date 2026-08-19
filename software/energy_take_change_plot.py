#!/usr/bin/env python3
"""Plot first-sample-relative EnergyTake and real power for one test run."""

from __future__ import annotations

import argparse
import csv
from datetime import time
from pathlib import Path

from matplotlib.figure import Figure

from .run_plot import plot_run


PLOT_FILENAME = "energy_take_change_power.png"


def plot_energy_take_change(
    run_directory: Path | str,
    *,
    scenario_start: time = time(15, 30),
    output_path: Path | str | None = None,
    show: bool = False,
    suppress_startup_spikes: bool = True,
) -> tuple[Figure, Path | None]:
    """Plot EnergyTake change from the run's first valid commodity sample."""
    return plot_run(
        run_directory,
        scenario_start=scenario_start,
        output_path=output_path,
        show=show,
        suppress_startup_spikes=suppress_startup_spikes,
        energy_change_from_start=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", default="15:30", help="scenario start in HH:MM")
    parser.add_argument("--show", action="store_true")
    parser.add_argument(
        "--include-startup-spikes",
        action="store_true",
        help="plot raw compressor-start inrush samples",
    )
    args = parser.parse_args()
    try:
        output = args.output or args.run_directory / PLOT_FILENAME
        _, destination = plot_energy_take_change(
            args.run_directory,
            scenario_start=time.fromisoformat(args.start),
            output_path=output,
            show=args.show,
            suppress_startup_spikes=not args.include_startup_spikes,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"ENERGY_TAKE_CHANGE_PLOT_ERROR {type(exc).__name__}: {exc}\n")
    print(f"ENERGY_TAKE_CHANGE_PLOT {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
