import csv
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from software.run_comparison_plot import plot_run_comparison


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


class RunComparisonPlotTests(unittest.TestCase):
    def create_run(self, directory, *, second_phase="shed", second_offset_hours=1):
        directory.mkdir()
        write_csv(
            directory / "master_schedule.csv",
            ["enabled", "event_id", "event_type", "action", "expected_operational_states"],
            [["TRUE", "alu", "cta", "advanced_load_up", "3|6"], ["TRUE", "event", "cta", second_phase, "2|4"]],
        )
        second_hour = 13 + second_offset_hours
        write_csv(
            directory / "cta_events.csv",
            ["timestamp_pacific", "event", "command", "result", "operational_state", "operational_state_name"],
            [
                ["2026-08-17T13:00:00-07:00", "intermediate_response", "advanced_load_up", "success", "", ""],
                ["2026-08-17T13:00:30-07:00", "operational_state", "query_operational_state", "received", "3", "Running Heightened"],
                [f"2026-08-17T{second_hour:02d}:00:00-07:00", "application_ack", second_phase, "ack", "", ""],
                [f"2026-08-17T{second_hour:02d}:00:30-07:00", "operational_state", "query_operational_state", "received", "4", "Idle Curtailed"],
                [f"2026-08-17T{second_hour + 1:02d}:00:00-07:00", "operational_state", "query_operational_state", "received", "4", "Idle Curtailed"],
            ],
        )
        write_csv(
            directory / "cta_commodity.csv",
            ["timestamp_pacific", "present_energy_storage_Wh", "advanced_present_energy_storage_Wh"],
            [["2026-08-17 13:00:00", "100", "1000"], [f"2026-08-17 {second_hour + 1:02d}:00:00", "100", "1800"]],
        )
        write_csv(
            directory / "power.csv",
            ["timestamp_pacific", "status", "record_reason", "real_power"],
            [["2026-08-17T13:00:00-07:00", "ok", "heartbeat", "100"], [f"2026-08-17T{second_hour + 1:02d}:00:00-07:00", "ok", "heartbeat", "200"]],
        )

    def test_saves_compatible_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "run_one_2026_08_17_130000_PDT"
            second = root / "run_two_2026_08_18_130000_PDT"
            self.create_run(first)
            self.create_run(second)
            output = root / "comparison.png"
            figure, destination = plot_run_comparison([first, second], output_path=output)
            self.assertEqual(destination, output.resolve())
            self.assertTrue(output.is_file())
            self.assertEqual(len(figure.axes), 3)
            self.assertEqual(list(figure.axes[1].lines[0].get_ydata()), [0.0, 0.8])

    def test_rejects_incompatible_phase_sequence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "run_one"
            second = root / "run_two"
            self.create_run(first)
            self.create_run(second, second_phase="critical_peak")
            with self.assertRaisesRegex(ValueError, "incompatible phase sequence"):
                plot_run_comparison([first, second])


if __name__ == "__main__":
    unittest.main()
