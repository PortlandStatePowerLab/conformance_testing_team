"""Export a paper overlay of hot-water temperature, power and water flow."""

from software.plots.paper_overlay_plot import main, plot_paper_overlay


def plot_paper_temperature_power_water(run_directory, *, width=3.5, height=2.8):
    return plot_paper_overlay(
        run_directory, series="temperature_power_water", width=width, height=height
    )


if __name__ == "__main__":
    main("temperature_power_water")
