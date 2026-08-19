import csv
import tempfile
import unittest
from datetime import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from software.run_plot import Sample, _without_startup_spikes, load_run_plot_data, plot_run
from software.energy_take_change_plot import plot_energy_take_change


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


class RunPlotTests(unittest.TestCase):
    def test_suppresses_only_isolated_compressor_startup_spike(self):
        from datetime import datetime, timedelta

        start = datetime(2026, 8, 3, 20, 38, 23)
        samples = (
            Sample(start, 18.0, "heartbeat"),
            Sample(start + timedelta(seconds=1), 918.0, "current_change|power_change|heater_on"),
            Sample(start + timedelta(seconds=2), 232.0, "current_change|power_change"),
            Sample(start + timedelta(seconds=3), 250.0, "current_change"),
            Sample(start + timedelta(seconds=4), 900.0, "current_change|power_change|heater_on"),
            Sample(start + timedelta(seconds=5), 850.0, "current_change"),
        )
        filtered = _without_startup_spikes(samples)
        self.assertEqual(
            [sample.value for sample in filtered],
            [18.0, 232.0, 250.0, 900.0, 850.0],
        )

    def test_suppresses_delayed_inrush_but_preserves_gradual_ramp(self):
        from datetime import datetime, timedelta

        start = datetime(2026, 8, 9, 14, 14, 35)
        samples = (
            Sample(start, 49.0, "current_change|power_change|heater_on"),
            Sample(start + timedelta(seconds=60), 49.0, "heartbeat"),
            Sample(start + timedelta(seconds=63), 2075.0, "current_change|power_change"),
            Sample(start + timedelta(seconds=64), 341.0, "current_change|power_change"),
            Sample(start + timedelta(seconds=65), 449.0, "current_change|power_change"),
            Sample(start + timedelta(seconds=67), 490.0, "current_change"),
        )
        filtered = _without_startup_spikes(samples)
        self.assertEqual(
            [sample.value for sample in filtered],
            [49.0, 49.0, 341.0, 449.0, 490.0],
        )

    def create_run(self, directory):
        write_csv(
            directory / "cta_events.csv",
            ["timestamp_pacific", "event", "command", "result"],
            [
                ["2026-08-17T12:59:01-07:00", "command_sent", "advanced_load_up", "pending"],
                ["2026-08-17T12:59:02-07:00", "link_ack", "advanced_load_up", "ack"],
                ["2026-08-17T12:59:03-07:00", "intermediate_response", "advanced_load_up", "success"],
                ["2026-08-17T14:29:03-07:00", "application_ack", "critical_peak", "ack"],
                ["2026-08-17T15:00:03-07:00", "application_ack", "grid_emergency", "ack"],
                ["2026-08-17T15:29:03-07:00", "application_ack", "shed", "ack"],
                ["2026-08-17T18:39:03-07:00", "intermediate_response", "advanced_load_up", "success"],
                ["2026-08-17T19:39:03-07:00", "application_ack", "run_normal", "ack"],
            ],
        )
        write_csv(
            directory / "cta_commodity.csv",
            ["timestamp_pacific", "present_energy_storage_Wh", "advanced_present_energy_storage_Wh"],
            [
                ["2026-08-17 12:59:00", "100", "1000"],
                ["2026-08-17 19:59:00", "200", "1500"],
            ],
        )
        write_csv(
            directory / "power.csv",
            ["timestamp_pacific", "status", "real_power"],
            [
                ["2026-08-17T12:59:00-07:00", "ok", "400"],
                ["2026-08-17T19:59:00-07:00", "ok", "10"],
            ],
        )

    def test_loads_advanced_energy_and_acknowledged_phases(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            data = load_run_plot_data(directory)
            self.assertEqual(data.energy_column, "advanced_present_energy_storage_Wh")
            self.assertEqual([sample.value for sample in data.energy], [1000.0, 1500.0])
            self.assertEqual(
                [phase.name for phase in data.phases],
                ["ALU", "CP", "GE", "Shed", "ALU", "Normal"],
            )

    def test_saves_plot(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            output = directory / "plot.png"
            figure, destination = plot_run(
                directory, scenario_start=time(15, 30), output_path=output
            )
            self.assertEqual(destination, output.resolve())
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 1000)
            self.assertEqual(len(figure.axes), 3)
            self.assertEqual(
                [text.get_text() for text in figure.axes[0].texts],
                ["ALU", "CP", "GE", "Shed", "ALU", "Normal"],
            )

    def test_energy_change_starts_at_zero_and_keeps_signed_axis(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            output = directory / "change.png"
            figure, destination = plot_energy_take_change(directory, output_path=output)
            energy_line = figure.axes[1].lines[0]
            self.assertEqual(list(energy_line.get_ydata()), [0.0, 0.5])
            self.assertEqual(destination, output.resolve())
            lower, upper = figure.axes[1].get_ylim()
            self.assertLessEqual(lower, 0)
            self.assertGreaterEqual(upper, 0)


if __name__ == "__main__":
    unittest.main()
