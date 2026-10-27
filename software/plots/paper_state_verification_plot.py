"""Single-column unfiltered operational-state verification; PDF + PNG."""

import argparse
from pathlib import Path

from software.plots.paper_style import equipment_name, paper_figure, save_paper, compact_clock_labels
from software.plots.run_plot import _duck_curve_display_start, _shift
from software.plots.state_verification_plot import load_verification_data, verification_status, _segments, StateReport
from software.plots.run_plot_water import STATUS_COLORS
from software.plots.time_axis import apply_even_clock_ticks


def plot_paper_state_verification(run_directory, *, width=3.5, height=3.2):
    data = load_verification_data(run_directory)
    start = min(data.reports[0].timestamp, data.phases[0].timestamp)
    end = max(data.reports[-1].timestamp, data.phases[-1].timestamp)
    end = min(end, data.verification_end or end)
    display = _duck_curve_display_start(start, data.phases)
    shifted = lambda timestamp: _shift(timestamp, start, display)
    reports = tuple(r for r in data.reports if r.timestamp < end)
    figure = paper_figure(width, height)
    axes = figure.subplots(3, 1, sharex=True, gridspec_kw={"hspace": .12})
    for index, phase in enumerate(data.phases):
        finish = data.phases[index + 1].timestamp if index + 1 < len(data.phases) else end
        axes[0].axvspan(shifted(phase.timestamp), shifted(finish), color="#dbe6ef")
        axes[0].axvline(shifted(phase.timestamp), color="0.4", linewidth=.5)
        axes[0].text(shifted(phase.timestamp + (finish - phase.timestamp) / 2), .5,
                     phase.name + "\n" + "|".join(str(c) for c in sorted(phase.expected_states)),
                     ha="center", va="center", fontsize=8)
    colors = {0: "#dbe6ef", 1: "#cfe8cf", 2: "#f8d58a", 3: "#b7ddb7", 4: "#efc875", 5: "#efaaaa", 6: "#9dcc9d"}
    for a, b, report in _segments(reports, lambda r: r.code, end):
        axes[1].axvspan(shifted(a), shifted(b), color=colors.get(report.code, "#dddddd"), linewidth=0)
        axes[1].axvline(shifted(a), color="0.4", linewidth=.4)
        if (b - a).total_seconds() > (end - start).total_seconds() * .09:
            axes[1].text(shifted(a + (b - a) / 2), .5, str(report.code), ha="center", va="center", fontsize=9)
    statuses = tuple(StateReport(r.timestamp, r.code, verification_status(r, data.phases)) for r in reports)
    for a, b, report in _segments(statuses, lambda r: r.name, end):
        axes[2].axvspan(shifted(a), shifted(b), color=STATUS_COLORS[report.name], linewidth=0)
        if (b - a).total_seconds() > (end - start).total_seconds() * .15:
            axes[2].text(shifted(a + (b - a) / 2), .5, report.name, ha="center", va="center", fontsize=9)
    for axis, label in zip(axes, ["Command\n(expected)", "Op State\n(reported)", "Verification"]):
        axis.set_ylabel(label, fontsize=8)
        axis.set_yticks([])
        axis.set_ylim(0, 1)
        axis.tick_params(axis="x", labelsize=8, labelbottom=axis is axes[-1])
        for spine in axis.spines.values():
            spine.set_linewidth(.5)
    axes[-1].set_xlim(display, shifted(end))
    apply_even_clock_ticks(axes[-1], display, shifted(end), count=3)
    compact_clock_labels(axes[-1])
    figure.suptitle(equipment_name(run_directory), fontsize=10, y=.98)
    figure.subplots_adjust(left=.27, right=.97, top=.89, bottom=.12)
    return figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--width", type=float, default=3.5)
    parser.add_argument("--height", type=float, default=3.2)
    args = parser.parse_args()
    figure = plot_paper_state_verification(args.run_directory, width=args.width, height=args.height)
    for path in save_paper(figure, args.run_directory, "paper_operational_state_verification", args.output_directory):
        print(path)


if __name__ == "__main__":
    main()
