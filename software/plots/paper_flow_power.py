"""Export water draw and power in the paper overlay layout."""

from software.plots.paper_overlay_plot import main, plot_paper_overlay


def plot_paper_flow_power(run_directory, *, width=3.5, height=2.8):
    return plot_paper_overlay(
        run_directory, series="flow_power", width=width, height=height
    )


if __name__ == "__main__":
    main("flow_power")
