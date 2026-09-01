import unittest
from unittest.mock import Mock

from software.run_plot_water import _legend_entries, load_water_flow


class RunPlotWaterTests(unittest.TestCase):
    def test_legend_entries_use_cross_version_axes_api(self):
        axis = Mock(spec=["get_legend_handles_labels"])
        axis.get_legend_handles_labels.return_value = (["energy", "power"], ["EnergyTake", "Real Power"])

        self.assertEqual(
            _legend_entries(axis),
            (["energy", "power"], ["EnergyTake", "Real Power"]),
        )

    def test_missing_water_files_produce_empty_overlay_data(self):
        directory = Mock()
        directory.glob.return_value = []

        self.assertEqual(load_water_flow(directory), [])
        directory.glob.assert_called_once_with("water_draw_*.csv")


if __name__ == "__main__":
    unittest.main()
