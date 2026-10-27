"""Paper overlays with the original run colors and filled power/flow series."""

import argparse
from pathlib import Path
from matplotlib.ticker import MaxNLocator

from software.plots.paper_style import paper_figure, equipment_name, style_axis, compact_clock_labels, save_paper
from software.plots.run_plot import load_run_plot_data, _without_startup_spikes, _duck_curve_display_start, _shift
from software.plots.run_plot_water import load_water_flow, STATUS_COLORS, _is_wh4
from software.plots.state_verification_plot import load_verification_data, verification_status, _segments, StateReport
from software.plots.time_axis import apply_even_clock_ticks


def plot_paper_overlay(run_directory, *, series="power", width=3.5, height=2.8):
    if series not in {"power", "flow", "power_water"}:
        raise ValueError("series must be power, flow or power_water")
    directory = Path(run_directory)
    data = load_run_plot_data(directory)
    verification = load_verification_data(directory)
    start = min(data.energy[0].timestamp, data.power[0].timestamp)
    end = max(data.energy[-1].timestamp, data.power[-1].timestamp)
    display = _duck_curve_display_start(start, data.phases)
    shift = lambda timestamp: _shift(timestamp, start, display)
    figure = paper_figure(width, height)
    command, energy, state = figure.subplots(
        3, 1, sharex=True, gridspec_kw={"height_ratios": [.12, 1, .12], "hspace": .05})
    other = energy.twinx()
    colors = {"ALU": "#cfe8cf", "Load Up": "#cfe8cf", "Shed": "#f8d58a",
              "CP": "#f8d58a", "GE": "#efaaaa", "Normal": "#dbe6ef"}
    for index, phase in enumerate(verification.phases):
        begin = start if index == 0 and (phase.timestamp - start).total_seconds() <= 60 else phase.timestamp
        finish = verification.phases[index + 1].timestamp if index + 1 < len(verification.phases) else end
        color = colors.get(phase.name, "#eeeeee") if phase.accepted else "white"
        command.axvspan(shift(begin), shift(finish), facecolor=color)
        energy.axvspan(shift(begin), shift(finish), color=color, alpha=.22, zorder=0)
        command.axvline(shift(begin), color=".4", linewidth=.5)
        energy.axvline(shift(begin), color=".4", linewidth=.4, alpha=.5)
        command.text(shift(begin + (finish - begin) / 2), .5,
                     phase.name if phase.accepted else phase.name + " (rejected)",
                     ha="center", va="center", fontsize=8, clip_on=True)
    energy.plot([shift(s.timestamp) for s in data.energy], [s.value / 1000 for s in data.energy],
                color="green", linewidth=.9, zorder=3)
    if series in {"power", "power_water"}:
        samples = _without_startup_spikes(data.power)
        times = [shift(s.timestamp) for s in samples]
        values = [s.value / 1000 for s in samples]
        color, label, alpha = "red", "Power (kW)", .18
    else:
        water = load_water_flow(directory)
        times = [shift(t) for t, _ in water]
        values = [v for _, v in water]
        color, label, alpha = "#1677b8", "Flow (gal/min)", .09
        if not water:
            other.text(.5, .95, "No water-draw data", transform=other.transAxes,
                       ha="center", va="top", fontsize=8)
    other.plot(times, values, color=color, linewidth=.7, alpha=.8)
    other.fill_between(times, values, color=color, alpha=alpha)
    for axis, text, tint in [(energy, "EnergyTake (kWh)", "green"), (other, label, color)]:
        axis.set_ylabel(text, color=tint, fontsize=9)
        style_axis(axis)
        axis.yaxis.set_major_locator(MaxNLocator(nbins=4, min_n_ticks=4))
        axis.tick_params(axis="y", colors=tint)
    energy.set_ylim(0, max(.1, max(s.value / 1000 for s in data.energy) * 1.12))
    other.set_ylim(0, max(.1, max(values, default=0) * 1.12))
    for axis in (energy, other):
        lower, upper = axis.get_ylim()
        axis.set_yticks([tick for tick in axis.get_yticks()
                         if lower < tick <= upper])
    other.grid(False)
    if series == "power_water":
        flow_axis = energy.twinx()
        flow_axis.spines["right"].set_position(("outward", 38))
        water = load_water_flow(directory)
        flow_times = [shift(t) for t, _ in water]
        flow_values = [v for _, v in water]
        flow_axis.plot(flow_times, flow_values, color="#1677b8", linewidth=.7, alpha=.8)
        flow_axis.fill_between(flow_times, flow_values, color="#1677b8", alpha=.09)
        flow_axis.set_ylabel("Flow (gal/min)", fontsize=9, color="#1677b8")
        style_axis(flow_axis)
        flow_axis.yaxis.set_major_locator(MaxNLocator(nbins=4, min_n_ticks=4))
        flow_axis.set_ylim(0, max(.1, max(flow_values, default=0) * 1.12))
        upper = flow_axis.get_ylim()[1]
        flow_axis.set_yticks([t for t in flow_axis.get_yticks() if 0 < t <= upper])
        flow_axis.tick_params(axis="y", colors="#1677b8")
        flow_axis.grid(False)
        if not water:
            flow_axis.text(.5, .95, "No water-draw data", transform=flow_axis.transAxes,
                           ha="center", va="top", fontsize=8)
    reports = [r for r in verification.reports if start <= r.timestamp < end
               and (verification.verification_end is None or r.timestamp < verification.verification_end)]
    if not _is_wh4(directory):
        reports = [r for i, r in enumerate(reports) if not (
            r.code == 5 and 0 < i < len(reports) - 1 and reports[i - 1].code != 5
            and (reports[i - 1].code, reports[i - 1].name) == (reports[i + 1].code, reports[i + 1].name))]
    for index, report in enumerate(reports):
        finish = reports[index + 1].timestamp if index + 1 < len(reports) else min(end, verification.verification_end or end)
        state.axvspan(shift(report.timestamp), shift(finish), linewidth=0,
                      color=STATUS_COLORS[verification_status(report, verification.phases)])
    statuses = tuple(StateReport(r.timestamp, r.code,
                                verification_status(r, verification.phases)) for r in reports)
    verification_end = min(end, verification.verification_end or end)
    for begin, finish, report in _segments(statuses, lambda r: r.name, verification_end):
        if (finish - begin).total_seconds() >= (end - start).total_seconds() * .15:
            state.text(shift(begin + (finish - begin) / 2), .5, report.name,
                       ha="center", va="center", fontsize=8, clip_on=True)
    for axis in [command, state]:
        axis.set_yticks([])
        axis.set_ylim(0, 1)
        for spine in axis.spines.values():
            spine.set_linewidth(.5)
    state.set_ylabel("Op\nState", fontsize=8, rotation=0, va="center", ha="right")
    state.yaxis.set_label_coords(-.06, .5)
    state.set_xlim(display, shift(end))
    apply_even_clock_ticks(state, display, shift(end), count=3)
    compact_clock_labels(state)
    for axis in [command, energy, state]:
        axis.tick_params(axis="x", labelsize=8, labelbottom=axis is state, bottom=axis is state)
    figure.suptitle(equipment_name(directory), fontsize=10, y=.98)
    figure.subplots_adjust(left=.20, right=.80, top=.89, bottom=.10)
    return figure


def plot_paper_energy_take_power_water(run_directory, *, width=3.5, height=2.8):
    """Preview all three series overlaid, retaining fills and command colors."""
    return plot_paper_overlay(run_directory, series="power_water", width=width, height=height)


def main(series):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--height", type=float, default=2.8)
    args = parser.parse_args()
    figure = plot_paper_overlay(args.run_directory, series=series, width=args.width, height=args.height)
    stem = {"power": "paper_energy_take_power", "flow": "paper_energy_take_flow",
            "power_water": "paper_energy_take_power_water_overlay"}[series]
    for path in save_paper(figure, args.run_directory, stem, args.output_directory):
        print(path)
