import unittest
from unittest.mock import Mock

from software.plots.run_plot_water import (
    MINIMUM_POWER_AXIS_MAX_KW,
    _legend_entries,
    _upper_with_headroom,
    load_water_flow,
)


class RunPlotWaterTests(unittest.TestCase):
    def test_dedicated_water_plot_keeps_water_axis_even_without_flow(self):
        import tempfile
        from pathlib import Path
        from datetime import time
        from test_run_plot import RunPlotTests
        from software.plots.run_plot_water import plot_run_with_water

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            RunPlotTests().create_run(directory)
            figure, _ = plot_run_with_water(directory, scenario_start=time(15, 30))
        self.assertEqual(len(figure.axes), 5)
        self.assertEqual(figure.axes[3].get_ylabel(), "Water Flow (GPM)")
        self.assertEqual(figure.axes[4].get_ylabel(), "Operational\nState")
        self.assertEqual(
            [text.get_text() for text in figure.axes[1].get_legend().get_texts()],
            ["EnergyTake", "Real Power", "Water Draw"],
        )

    def test_axis_headroom_scales_above_data(self):
        self.assertAlmostEqual(_upper_with_headroom([0.5, 1.0]), 1.18)
        self.assertEqual(_upper_with_headroom([0.004], minimum=0.1), 0.1)

    def test_power_axis_floor_is_one_tenth_kw(self):
        self.assertEqual(MINIMUM_POWER_AXIS_MAX_KW, 0.1)

    def test_legend_entries_use_cross_version_axes_api(self):
        axis = Mock(spec=["get_legend_handles_labels"])
        axis.get_legend_handles_labels.return_value = (["energy", "power"], ["EnergyTake", "Real Power"])

        self.assertEqual(
            _legend_entries(axis),
            (["energy", "power"], ["EnergyTake", "Real Power"]),
        )
        axis.get_legend_handles_labels.assert_called_once_with()

    def test_missing_water_files_produce_empty_overlay_data(self):
        directory = Mock()
        directory.glob.return_value = []

        self.assertEqual(load_water_flow(directory), [])
        directory.glob.assert_called_once_with("water_draw_*.csv")


if __name__ == "__main__":
    unittest.main()
