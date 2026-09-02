import csv
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from software.phase_summary_plot import plot_phase_summary, summarize_run_phases


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


class PhaseSummaryPlotTests(unittest.TestCase):
    def create_run(self, directory):
        write_csv(
            directory / "master_schedule.csv",
            ["enabled", "event_id", "event_type", "action", "expected_operational_states"],
            [
                ["TRUE", "alu_1", "cta", "advanced_load_up", "3|6"],
                ["TRUE", "shed_1", "cta", "shed", "2|4"],
                ["TRUE", "alu_2", "cta", "advanced_load_up", "3|6"],
            ],
        )
        write_csv(
            directory / "cta_events.csv",
            ["timestamp_pacific", "event", "command", "result", "operational_state", "operational_state_name"],
            [
                ["2026-08-17T12:59:00-07:00", "intermediate_response", "advanced_load_up", "success", "", ""],
                ["2026-08-17T12:59:30-07:00", "operational_state", "query_operational_state", "received", "3", "Running Heightened"],
                ["2026-08-17T13:59:00-07:00", "application_ack", "shed", "ack", "", ""],
                ["2026-08-17T13:59:30-07:00", "operational_state", "query_operational_state", "received", "4", "Idle Curtailed"],
                ["2026-08-17T14:59:00-07:00", "intermediate_response", "advanced_load_up", "success", "", ""],
                ["2026-08-17T14:59:30-07:00", "operational_state", "query_operational_state", "received", "0", "Idle Normal"],
                ["2026-08-17T15:01:00-07:00", "operational_state", "query_operational_state", "received", "0", "Idle Normal"],
            ],
        )
        write_csv(
            directory / "cta_commodity.csv",
            ["timestamp_pacific", "present_energy_storage_Wh", "advanced_present_energy_storage_Wh"],
            [
                ["2026-08-17 12:59:00", "100", "1000"],
                ["2026-08-17 13:59:00", "100", "1500"],
                ["2026-08-17 14:59:00", "100", "900"],
                ["2026-08-17 15:01:00", "100", "800"],
            ],
        )
        write_csv(
            directory / "power.csv",
            ["timestamp_pacific", "status", "record_reason", "real_power"],
            [
                ["2026-08-17T12:59:00-07:00", "ok", "heartbeat", "100"],
                ["2026-08-17T13:59:00-07:00", "ok", "heartbeat", "0"],
                ["2026-08-17T14:59:00-07:00", "ok", "heartbeat", "200"],
                ["2026-08-17T15:01:00-07:00", "ok", "heartbeat", "200"],
            ],
        )

    def test_calculates_numbered_phase_metrics_and_state_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            summaries = summarize_run_phases(directory)
            self.assertEqual([item.phase for item in summaries], ["ALU 1", "Shed", "ALU 2"])
            self.assertAlmostEqual(summaries[0].change_energy_kwh, 0.5)
            self.assertAlmostEqual(summaries[1].change_energy_kwh, -0.6)
            self.assertEqual([item.state_result for item in summaries], ["Pass", "Pass", "Fail"])

    def test_saves_phase_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            output = directory / "phase_summary.png"
            figure, destination = plot_phase_summary(directory, output_path=output)
            self.assertEqual(destination, output.resolve())
            self.assertTrue(output.is_file())
            self.assertEqual(len(figure.axes), 2)

    def test_cleanup_run_normal_does_not_fail_last_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            with (directory / "master_schedule.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.reader(handle))
            rows[-1][-1] = "0|1"
            write_csv(directory / "master_schedule.csv", rows[0], rows[1:])
            with (directory / "cta_events.csv").open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows([
                    ["2026-08-17T15:00:00-07:00", "application_ack", "run_normal", "ack", "", ""],
                    ["2026-08-17T15:00:30-07:00", "operational_state", "query_operational_state", "received", "5", "SGD Error Condition"],
                ])

            summaries = summarize_run_phases(directory)

            self.assertEqual(summaries[-1].state_result, "Pass")
            self.assertEqual(summaries[-1].duration_seconds, 60)


if __name__ == "__main__":
    unittest.main()
