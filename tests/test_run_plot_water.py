import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import unittest
from unittest.mock import Mock, patch

from software.plots.run_plot_water import (
    MINIMUM_POWER_AXIS_MAX_KW,
    _legend_entries,
    _upper_with_headroom,
    load_water_flow,
    plot_run_with_water,
)


class RunPlotWaterTests(unittest.TestCase):
    def test_water_axis_requires_positive_flow(self):
        from test_run_plot import RunPlotTests, write_csv

        for flows in (None, [], [0, 0], [float("nan"), -1], [0, 1.5]):
            with self.subTest(flows=flows), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                RunPlotTests().create_run(directory)
                if flows is not None:
                    write_csv(
                        directory / "water_draw_001.csv",
                        ["timestamp_pacific", "flow_gpm"],
                        [[f"2026-08-17 13:00:0{index}", value]
                         for index, value in enumerate(flows)],
                    )
                with patch(
                    "software.plots.run_plot_water.load_verification_data",
                    return_value=Mock(reports=(), phases=(), verification_end=None),
                ):
                    figure, _ = plot_run_with_water(directory)
                try:
                    expected = flows == [0, 1.5]
                    self.assertEqual(
                        "Water Flow (GPM)" in [axis.get_ylabel() for axis in figure.axes],
                        expected,
                    )
                    labels = [text.get_text() for text in figure.axes[1].get_legend().get_texts()]
                    self.assertEqual("Water Draw" in labels, expected)
                    self.assertEqual(figure.axes[-1].get_ylabel(), "Operational\nState")
                    self.assertEqual(len(figure.axes), 5 if expected else 4)
                finally:
                    plt.close(figure)

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
