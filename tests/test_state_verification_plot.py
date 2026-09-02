import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from software.state_verification_plot import (
    StateReport,
    load_verification_data,
    plot_state_verification,
    verification_status,
)


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


class StateVerificationPlotTests(unittest.TestCase):
    def create_run(self, directory):
        write_csv(
            directory / "master_schedule.csv",
            ["enabled", "event_id", "event_type", "action", "expected_operational_states"],
            [
                ["TRUE", "alu_1", "cta", "advanced_load_up", "3|6"],
                ["TRUE", "shed_1", "cta", "shed", "2|4"],
                ["TRUE", "normal_1", "cta", "run_normal", "0|1"],
            ],
        )
        write_csv(
            directory / "cta_events.csv",
            ["timestamp_pacific", "event", "command", "result", "operational_state", "operational_state_name"],
            [
                ["2026-08-17T12:59:00-07:00", "operational_state", "query_operational_state", "received", "0", "Idle Normal"],
                ["2026-08-17T12:59:15-07:00", "intermediate_response", "advanced_load_up", "success", "", ""],
                ["2026-08-17T12:59:30-07:00", "operational_state", "query_operational_state", "received", "0", "Idle Normal"],
                ["2026-08-17T13:00:30-07:00", "operational_state", "query_operational_state", "received", "3", "Running Heightened"],
                ["2026-08-17T15:29:15-07:00", "application_ack", "shed", "ack", "", ""],
                ["2026-08-17T15:29:30-07:00", "operational_state", "query_operational_state", "received", "4", "Idle Curtailed"],
                ["2026-08-17T16:00:00-07:00", "application_ack", "run_normal", "ack", "", ""],
                ["2026-08-17T16:00:30-07:00", "operational_state", "query_operational_state", "received", "0", "Idle Normal"],
                ["2026-08-17T16:10:00-07:00", "application_ack", "run_normal", "ack", "", ""],
            ],
        )

    def test_loads_only_scheduled_acknowledgments(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            data = load_verification_data(directory)
            self.assertEqual([phase.name for phase in data.phases], ["ALU", "Shed", "Normal"])
            self.assertEqual(data.phases[0].expected_states, frozenset({3, 6}))
            self.assertEqual(
                data.verification_end,
                datetime(2026, 8, 17, 16, 10),
            )

    def test_grace_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            data = load_verification_data(directory)
            phase = data.phases[0]
            self.assertEqual(
                verification_status(StateReport(phase.timestamp, 0, "Idle Normal"), data.phases),
                "Grace",
            )
            self.assertEqual(
                verification_status(StateReport(datetime(2026, 8, 17, 13, 0, 30), 3, "Running Heightened"), data.phases),
                "Pass",
            )
            self.assertEqual(
                verification_status(StateReport(datetime(2026, 8, 17, 13, 0, 30), 0, "Idle Normal"), data.phases),
                "Fail",
            )

    def test_saves_plot(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            output = directory / "states.png"
            figure, destination = plot_state_verification(directory, output_path=output)
            self.assertEqual(destination, output.resolve())
            self.assertTrue(output.is_file())
            self.assertEqual(len(figure.axes), 3)

    def test_rejected_scheduled_phase_is_preserved_and_fails_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            write_csv(
                directory / "master_schedule.csv",
                ["enabled", "event_id", "event_type", "action", "expected_operational_states"],
                [
                    ["TRUE", "alu_1", "cta", "advanced_load_up", "3|6"],
                    ["TRUE", "shed_1", "cta", "shed", "2|4"],
                    ["TRUE", "alu_2", "cta", "advanced_load_up", "3|6"],
                    ["TRUE", "normal_1", "cta", "run_normal", "0|1"],
                ],
            )
            with (directory / "cta_events.csv").open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows([
                    ["2026-08-17T15:45:00-07:00", "command_completed", "advanced_load_up", "bad_value", "", ""],
                ])
            data = load_verification_data(directory)
            rejected = [phase for phase in data.phases if not phase.accepted]
            self.assertEqual([(phase.name, phase.result) for phase in rejected], [("ALU", "bad_value")])
            report = StateReport(rejected[0].timestamp, 3, "Running Heightened")
            self.assertEqual(verification_status(report, data.phases), "Fail")


if __name__ == "__main__":
    unittest.main()
