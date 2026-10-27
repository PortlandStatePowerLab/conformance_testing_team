"""Single-column EnergyTake, power, water and Op State panels; PDF + PNG."""

import argparse
from datetime import time
from pathlib import Path
from matplotlib.ticker import MaxNLocator

from software.plots.paper_style import equipment_name, paper_figure, save_paper, style_axis, compact_clock_labels
from software.plots.run_plot import load_run_plot_data, _without_startup_spikes, _duck_curve_display_start, _shift
from software.plots.run_plot_water import load_water_flow, STATUS_COLORS, _is_wh4
from software.plots.state_verification_plot import load_verification_data, verification_status, _segments, StateReport
from software.plots.time_axis import apply_even_clock_ticks


def plot_paper_run(run_directory, *, width=3.5, height=5.5, scenario_start=None,
                   include_isolated_state5=False):
    directory = Path(run_directory)
    data = load_run_plot_data(directory)
    verification = load_verification_data(directory)
    start = min(data.energy[0].timestamp, data.power[0].timestamp)
    end = max(data.energy[-1].timestamp, data.power[-1].timestamp)
    display = _duck_curve_display_start(start, data.phases, scenario_start=scenario_start)
    shifted = lambda timestamp: _shift(timestamp, start, display)
    figure = paper_figure(width, height)
    axes = figure.subplots(5, 1, sharex=True,
                           gridspec_kw={"height_ratios": [0.45, 1, 1, 1, 0.5], "hspace": 0.16})
    phase_axis, energy_axis, power_axis, water_axis, state_axis = axes
    phase_colors = {"ALU": "#cfe8cf", "Load Up": "#cfe8cf", "Shed": "#f8d58a",
                    "CP": "#f8d58a", "GE": "#efaaaa", "Normal": "#dbe6ef"}
    for index, phase in enumerate(verification.phases):
        begin = start if index == 0 and (phase.timestamp - start).total_seconds() <= 60 else phase.timestamp
        finish = verification.phases[index + 1].timestamp if index + 1 < len(verification.phases) else end
        color = phase_colors.get(phase.name, "#eeeeee") if phase.accepted else "white"
        phase_axis.axvspan(shifted(begin), shifted(finish), color=color)
        for axis in (energy_axis, power_axis, water_axis):
            axis.axvspan(shifted(begin), shifted(finish), color=color, alpha=.22, zorder=0)
            axis.axvline(shifted(begin), color="0.4", linewidth=.4, alpha=.5)
        phase_axis.axvline(shifted(begin), color="0.4", linewidth=0.5)
        phase_axis.text(shifted(begin + (finish - begin) / 2), .5,
                        phase.name + ("\nRejected" if not phase.accepted else ""),
                        ha="center", va="center", fontsize=8)
    energy_axis.step([shifted(s.timestamp) for s in data.energy],
                     [s.value / 1000 for s in data.energy], where="post", color="green", linewidth=.8)
    power = _without_startup_spikes(data.power)
    power_axis.step([shifted(s.timestamp) for s in power], [s.value / 1000 for s in power],
                    where="post", color="red", linewidth=.7)
    power_axis.fill_between([shifted(s.timestamp) for s in power],
                            [s.value / 1000 for s in power], step="post", color="red", alpha=.18)
    water = load_water_flow(directory)
    if water:
        water_axis.plot([shifted(t) for t, _ in water], [v for _, v in water],
                        color="#1677b8", linewidth=.7)
        water_axis.fill_between([shifted(t) for t, _ in water], [v for _, v in water],
                                color="#1677b8", alpha=.09)
    else:
        water_axis.text(.5, .5, "No water-draw data", transform=water_axis.transAxes,
                        ha="center", fontsize=8)
    for axis, label in [(energy_axis, "EnergyTake\n(kWh)"),
                        (power_axis, "Power\n(kW)"), (water_axis, "Flow\n(gal/min)")]:
        axis.set_ylabel(label, fontsize=9)
        axis.set_ylim(bottom=0)
        style_axis(axis)
    for axis, color in [(energy_axis, "green"), (power_axis, "red"), (water_axis, "#1677b8")]:
        axis.yaxis.label.set_color(color)
        axis.tick_params(axis="y", colors=color)
        upper = axis.get_ylim()[1]
        # Choose three readable positive ticks, retaining zero as the baseline.
        ticks = MaxNLocator(nbins=3).tick_values(0, upper)
        positive = [tick for tick in ticks if tick > 0][:3]
        axis.set_ylim(0, max(upper, positive[-1]))
        axis.set_yticks(positive)
    reports = [r for r in verification.reports if start <= r.timestamp < end
               and (verification.verification_end is None or r.timestamp < verification.verification_end)]
    if not include_isolated_state5 and not _is_wh4(directory):
        reports = [r for i, r in enumerate(reports) if not (
            r.code == 5 and 0 < i < len(reports) - 1
            and reports[i - 1].code != 5
            and (reports[i - 1].code, reports[i - 1].name) == (reports[i + 1].code, reports[i + 1].name))]
    for index, report in enumerate(reports):
        finish = reports[index + 1].timestamp if index + 1 < len(reports) else min(end, verification.verification_end or end)
        state_axis.axvspan(shifted(report.timestamp), shifted(finish),
                          color=STATUS_COLORS[verification_status(report, verification.phases)], linewidth=0)
    statuses = tuple(StateReport(r.timestamp, r.code, verification_status(r, verification.phases))
                     for r in reports)
    for begin, finish, report in _segments(statuses, lambda r: r.name,
                                          min(end, verification.verification_end or end)):
        if (finish - begin).total_seconds() >= (end - start).total_seconds() * .15:
            state_axis.text(shifted(begin + (finish - begin) / 2), .5, report.name,
                            ha="center", va="center", fontsize=8, clip_on=True)
    for axis, label in [(phase_axis, "Command"), (state_axis, "Op State")]:
        axis.set_ylim(0, 1)
        axis.set_yticks([])
        axis.set_ylabel(label, fontsize=8)
    state_axis.set_xlim(display, shifted(end))
    apply_even_clock_ticks(state_axis, display, shifted(end), count=3)
    compact_clock_labels(state_axis)
    for axis in axes:
        axis.tick_params(axis="x", labelsize=8, labelbottom=axis is state_axis)
        for spine in axis.spines.values():
            spine.set_linewidth(.5)
    figure.suptitle(equipment_name(directory), fontsize=10, y=.985)
    figure.subplots_adjust(left=.25, right=.97, top=.94, bottom=.07)
    return figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--width", type=float, default=3.5, help="final printed width in inches")
    parser.add_argument("--height", type=float, default=5.5)
    parser.add_argument("--start", type=time.fromisoformat)
    parser.add_argument("--include-isolated-state5", action="store_true",
                        help="retain brief errors; default matches the screen combined plot")
    args = parser.parse_args()
    figure = plot_paper_run(args.run_directory, width=args.width, height=args.height,
                            scenario_start=args.start, include_isolated_state5=args.include_isolated_state5)
    for path in save_paper(figure, args.run_directory, "paper_energy_take_power_water", args.output_directory):
        print(path)


if __name__ == "__main__":
    main()
