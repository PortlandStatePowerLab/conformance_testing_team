import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import matplotlib.dates as mdates
from matplotlib.figure import Figure

from software.plots.temperature_power_water_trimmed import build_figure, cutoff_timestamp


class TrimmedTemperaturePlotTests(unittest.TestCase):
    def test_cutoff_uses_latest_stop_not_filename_order(self):
        with patch("software.plots.temperature_power_water_trimmed.load_draws", return_value=[
            SimpleNamespace(stop=datetime(2026, 11, 16, 16, 13, 6)),
            SimpleNamespace(stop=datetime(2026, 11, 16, 14, 30)),
        ]):
            self.assertEqual(cutoff_timestamp(Path("run")), datetime(2026, 11, 16, 16, 43, 6))

    def test_empty_run_has_no_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "no recorded water draws"):
                cutoff_timestamp(Path(directory))

    def test_trim_keeps_scales_and_recenters_visible_command_and_state(self):
        start, end, cutoff = (datetime(2026, 11, 16, hour) for hour in (12, 18, 15))
        figure = Figure()
        command, main, state = figure.subplots(3)
        main.twinx()
        # Make the state band last, as in the standard template.
        figure.delaxes(state)
        state = figure.add_subplot(313)
        for axis in (command, state):
            axis.axvspan(start, end, color="green")
            axis.text(datetime(2026, 11, 16, 16), .5, "Shed")
        main.set_xlim(start, end)
        main.set_ylim(60, 140)
        data = SimpleNamespace(energy=[SimpleNamespace(timestamp=start)],
                               power=[SimpleNamespace(timestamp=start)], phases=())
        module = "software.plots.temperature_power_water_trimmed."
        with patch(module + "cutoff_timestamp", return_value=cutoff), patch(
            module + "load_run_plot_data", return_value=data
        ), patch(module + "_duck_curve_display_start", return_value=start), patch(
            module + "full_figure", return_value=figure
        ):
            result = build_figure(Path("run"))
        self.assertIs(result, figure)
        self.assertEqual(main.get_ylim(), (60, 140))
        for axis in result.axes:
            self.assertAlmostEqual(axis.get_xlim()[1], mdates.date2num(cutoff))
        midpoint = (mdates.date2num(start) + mdates.date2num(cutoff)) / 2
        for axis in (command, state):
            self.assertTrue(axis.texts[0].get_visible())
            self.assertAlmostEqual(axis.texts[0].get_position()[0], midpoint)
        figure.clear()
