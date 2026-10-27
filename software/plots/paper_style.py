"""Shared final-print sizing and export for single-column paper figures."""

import json
import re
from pathlib import Path

from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from matplotlib.dates import DateFormatter


def compact_clock_labels(axis):
    axis.xaxis.set_major_formatter(DateFormatter("%H:%M"))
    labels = axis.get_xticklabels()
    if labels:
        labels[0].set_ha("left")
        labels[-1].set_ha("right")


def paper_figure(width, height):
    if width <= 0 or height <= 0:
        raise ValueError("figure dimensions must be positive")
    with rc_context({"font.size": 9, "axes.labelsize": 9,
                     "xtick.labelsize": 8, "ytick.labelsize": 8,
                     "axes.linewidth": 0.6, "pdf.fonttype": 42}):
        figure = Figure(figsize=(width, height))
        FigureCanvasAgg(figure)
    return figure


def equipment_name(directory):
    directory = Path(directory)
    path = Path(directory) / "equipment.json"
    name = ""
    if path.exists():
        name = json.loads(path.read_text(encoding="utf-8-sig")).get("display_name", "")
    test = re.split(r"_\d{4}_\d{2}_\d{2}(?:_|$)", directory.name)[0]
    test = re.split(r"-Recovery(?:-|$)", test, flags=re.IGNORECASE)[0]
    test = re.sub(r"_WH[_-]?\d+$", "", test, flags=re.IGNORECASE)
    return f"{test} — {name}" if name else test


def style_axis(axis):
    axis.tick_params(labelsize=8, width=0.6, length=3)
    axis.yaxis.label.set_size(9)
    axis.xaxis.label.set_size(9)
    axis.yaxis.set_major_locator(MaxNLocator(nbins=3, min_n_ticks=2))
    for spine in axis.spines.values():
        spine.set_linewidth(0.6)
    axis.grid(axis="y", alpha=0.2, linewidth=0.4)


def save_paper(figure, directory, stem, output_directory=None):
    """Fit content to the page width with a tiny margin; retain print sizing."""
    # Measure rendered labels rather than reserving generous fixed side margins.
    # Expand the axes, keeping the PDF at its requested physical width.
    width = figure.get_figwidth()
    for _ in range(3):
        figure.canvas.draw()
        bounds = figure.get_tightbbox(figure.canvas.get_renderer())
        left = figure.subplotpars.left + (0.025 - bounds.x0) / width
        right = figure.subplotpars.right + (width - 0.025 - bounds.x1) / width
        if 0 < left < right < 1:
            figure.subplots_adjust(left=left, right=right)
    destination = Path(output_directory or directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for extension in ("pdf", "png"):
        path = destination / f"{stem}.{extension}"
        with rc_context({"pdf.fonttype": 42}):
            figure.savefig(path, dpi=300)
        paths.append(path)
    return tuple(paths)
