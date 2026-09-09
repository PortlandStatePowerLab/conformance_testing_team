import unittest
from unittest.mock import Mock

from software.run_plot_water import (
    MINIMUM_POWER_AXIS_MAX_KW,
    _legend_entries,
    _upper_with_headroom,
    load_water_flow,
)


class RunPlotWaterTests(unittest.TestCase):
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
