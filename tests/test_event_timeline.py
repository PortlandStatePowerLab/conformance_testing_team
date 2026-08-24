import csv
import json
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from software.event_timeline import (
    _mode,
    _power_points,
    build_event_timeline,
    plot_event_timeline,
)


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


class EventTimelineTests(unittest.TestCase):
    def test_current_classifier_uses_gray_areas_and_hysteresis(self):
        self.assertEqual(_mode(0.10), "standby")
        self.assertEqual(_mode(0.25), "fan")
        self.assertEqual(_mode(0.60), "ramp")
        self.assertEqual(_mode(1.00), "compressor")
        self.assertEqual(_mode(10.0), "unexpected")
        self.assertEqual(_mode(17.5), "element")
        self.assertEqual(_mode(20.0), "combined")
        self.assertEqual(_mode(0.90, "compressor"), "compressor")
        self.assertEqual(_mode(0.70, "compressor"), "ramp")
        self.assertEqual(_mode(0.17, "fan"), "fan")
        self.assertEqual(_mode(0.14, "fan"), "standby")

    def test_suppresses_one_second_compressor_inrush(self):
        rows = [
            {"timestamp_pacific": "2026-08-17T12:00:00-07:00", "status": "ok", "current_rms": "0.3", "real_power": "60"},
            {"timestamp_pacific": "2026-08-17T12:00:10-07:00", "status": "ok", "current_rms": "27.9", "real_power": "2950"},
            {"timestamp_pacific": "2026-08-17T12:00:11-07:00", "status": "ok", "current_rms": "2.15", "real_power": "289"},
        ]
        self.assertEqual([point.mode for point in _power_points(rows)], ["fan", "compressor", "compressor"])

    def create_run(self, directory):
        write_csv(
            directory / "master_schedule.csv",
            ["enabled", "event_id", "event_type", "action", "expected_operational_states"],
            [
                ["TRUE", "alu_1", "cta", "advanced_load_up", "3|6"],
                ["TRUE", "shed_1", "cta", "shed", "2|4"],
            ],
        )
        write_csv(
            directory / "cta_events.csv",
            ["timestamp_pacific", "event", "command", "result", "operational_state", "operational_state_name"],
            [
                ["2026-08-17T12:00:00-07:00", "intermediate_response", "advanced_load_up", "success", "", ""],
                ["2026-08-17T12:00:33-07:00", "operational_state", "query_operational_state", "received", "6", "Idle Heightened"],
                ["2026-08-17T12:10:00-07:00", "application_ack", "shed", "ack", "", ""],
                ["2026-08-17T12:10:22-07:00", "operational_state", "query_operational_state", "received", "4", "Idle Curtailed"],
            ],
        )
        write_csv(
            directory / "cta_commodity.csv",
            ["timestamp_pacific", "present_energy_storage_Wh", "advanced_present_energy_storage_Wh"],
            [
                ["2026-08-17 12:00:01", "100", "300"],
                ["2026-08-17 12:01:00", "100", "270"],
                ["2026-08-17 12:11:00", "130", "300"],
            ],
        )
        write_csv(
            directory / "power.csv",
            ["timestamp_pacific", "status", "record_reason", "current_rms", "real_power"],
            [
                ["2026-08-17T11:59:59-07:00", "ok", "initial_sample", "0.10", "5"],
                ["2026-08-17T12:00:14-07:00", "ok", "current_change", "0.30", "60"],
                ["2026-08-17T12:00:40-07:00", "ok", "current_change", "0.60", "140"],
                ["2026-08-17T12:01:20-07:00", "ok", "heater_on", "2.50", "600"],
                ["2026-08-17T12:05:00-07:00", "ok", "heater_off", "0.10", "5"],
                ["2026-08-17T12:11:00-07:00", "ok", "heartbeat", "0.10", "5"],
            ],
        )
        write_csv(
            directory / "orchestrator_events.csv",
            ["timestamp_pacific", "test_elapsed_seconds", "event_id", "event", "status", "details"],
            [
                ["2026-08-17T12:02:00-07:00", "120", "water_draw_1", "water_draw_started", "ok", json.dumps({"target_volume_gal": 2.0})],
                ["2026-08-17T12:02:30-07:00", "150", "water_draw_1", "water_draw_completed", "ok", json.dumps({"return_code": 0})],
            ],
        )
        write_csv(
            directory / "water_draw_1.csv",
            ["timestamp_pacific", "accumulated_volume_gal"],
            [["2026-08-17T12:02:30-07:00", "2.01"]],
        )

    def test_builds_command_relative_milestones_and_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "WH-3" / "run"
            directory.mkdir(parents=True)
            self.create_run(directory)
            events = build_event_timeline(directory)
            by_name = {event.milestone: event for event in events}
            self.assertEqual(by_name["Fan started"].after_command_seconds, 14)
            self.assertEqual(by_name["Compressor ramp started"].after_command_seconds, 40)
            self.assertEqual(by_name["Compressor started"].after_command_seconds, 80)
            self.assertEqual(
                by_name["Expected operational state first observed"].after_command_seconds,
                22,
            )
            self.assertEqual(by_name["water_draw_1 completed"].observation, "Measured 2.01 gal")

            image = directory / "timeline.png"
            csv_path = directory / "timeline.csv"
            _, destination, csv_destination = plot_event_timeline(
                directory, output_path=image, csv_output_path=csv_path
            )
            self.assertEqual(destination, image.resolve())
            self.assertEqual(csv_destination, csv_path.resolve())
            self.assertTrue(image.is_file())
            self.assertTrue(csv_path.is_file())


if __name__ == "__main__":
    unittest.main()
