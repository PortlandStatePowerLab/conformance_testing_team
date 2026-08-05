import csv
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from software.conformance_report import (
    REPORT_FILENAME,
    SPREADSHEET_NS,
    build_commodity_summary,
    build_timeline,
    generate_conformance_report,
)


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


class ConformanceReportTests(unittest.TestCase):
    def create_run(self, directory):
        write_csv(
            directory / "cta_events.csv",
            ["timestamp_pacific", "event_id", "event", "command", "result", "operational_state", "operational_state_name"],
            [
                ["2026-08-03T10:00:00-07:00", "", "controller_started", "controller", "started", "", ""],
                ["2026-08-03T10:00:01-07:00", "load_1", "command_sent", "load_up", "pending", "", ""],
                ["2026-08-03T10:00:02-07:00", "load_1", "command_completed", "load_up", "ok", "", ""],
                ["2026-08-03T10:00:03-07:00", "", "operational_state", "query_operational_state", "received", "3", "Running Heightened"],
                ["2026-08-03T10:01:03-07:00", "", "operational_state", "query_operational_state", "received", "3", "Running Heightened"],
                ["2026-08-03T10:02:03-07:00", "", "operational_state", "query_operational_state", "received", "1", "Running Normal"],
            ],
        )
        write_csv(
            directory / "power.csv",
            ["timestamp_pacific", "status", "record_reason", "voltage_rms", "current_rms", "real_power", "reactive_power", "apparent_power", "power_factor"],
            [
                ["2026-08-03T10:00:00.500-07:00", "ok", "initial_sample", "241.0", "1.8", "430", "40", "432", "0.99"],
                ["2026-08-03T10:01:00.500-07:00", "ok", "heartbeat", "241.0", "1.8", "430", "40", "432", "0.99"],
                ["2026-08-03T10:01:05.500-07:00", "ok", "power_change", "241.1", "0.1", "10", "5", "11", "0.90"],
                ["2026-08-03T10:01:06.500-07:00", "i2c_error", "i2c_error", "", "", "", "", "", ""],
            ],
        )
        water_rows = [
            [f"2026-08-03T10:00:{10 + index:02d}-07:00", f"{index / 10:.6f}", "3.123456", "50.00", "122.00", "20.00", "68.00", "22.00", "71.60"]
            for index in range(10)
        ]
        write_csv(
            directory / "water_draw_1.csv",
            ["timestamp_pacific", "accumulated_volume_gal", "flow_gpm", "hot_temp_c", "hot_temp_f", "cold_temp_c", "cold_temp_f", "ambient_temp_c", "ambient_temp_f"],
            water_rows,
        )
        write_csv(
            directory / "orchestrator_events.csv",
            ["timestamp_pacific", "event_id", "event", "status"],
            [
                ["2026-08-03T10:00:09-07:00", "water_draw_1", "water_draw_started", "started"],
                ["2026-08-03T10:00:20-07:00", "water_draw_1", "water_draw_completed", "ok"],
            ],
        )
        write_csv(
            directory / "cta_device_information.csv",
            ["timestamp_pacific", "manufacturer_id", "model_number"],
            [["2026-08-03T10:00:00-07:00", "1", "WH-Test"]],
        )
        write_csv(
            directory / "master_schedule.csv",
            ["enabled", "event_id", "time_after_start", "event_type", "action"],
            [["TRUE", "load_1", "00:00:00", "cta", "load_up"]],
        )
        write_csv(
            directory / "cta_commodity.csv",
            ["cumulative_electricity_Wh", "total_energy_storage_Wh", "present_energy_storage_Wh", "advanced_total_energy_storage_Wh", "advanced_present_energy_storage_Wh"],
            [["100", "4000", "300", "", ""], ["125", "4000", "250", "", ""]],
        )

    def test_timeline_filters_and_samples_water(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            timeline = build_timeline(directory)

        self.assertEqual(sum(row["event"] == "operational_state" for row in timeline), 2)
        self.assertEqual(sum(row["event"] == "command_sent" for row in timeline), 1)
        self.assertEqual(sum(row["event"] == "command_completed" for row in timeline), 1)
        self.assertFalse(any(row["timestamp_pacific"].endswith("10:01:00.500-07:00") for row in timeline))
        water = [row for row in timeline if row["flow_gpm"] != ""]
        self.assertEqual(len(water), 4)
        self.assertEqual([row["accumulated_volume_gal"] for row in water], [0.0, 0.4, 0.8, 0.9])
        timestamps = [row["timestamp_pacific"] for row in timeline]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_commodity_is_reduced_to_summary_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            summary = {
                row["metric"]: row["value"]
                for row in build_commodity_summary(directory / "cta_commodity.csv")
            }

        self.assertEqual(summary["cumulative_electricity_change_Wh"], 25.0)
        self.assertEqual(summary["present_energy_storage_minimum_Wh"], 250.0)
        self.assertEqual(summary["present_energy_storage_maximum_Wh"], 300.0)
        self.assertEqual(summary["advanced_total_energy_storage_Wh"], "")

    def test_report_contains_four_named_sheets(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_run(directory)
            report = generate_conformance_report(directory)
            self.assertEqual(report.name, REPORT_FILENAME)
            with zipfile.ZipFile(report) as archive:
                workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))

        names = [
            sheet.attrib["name"]
            for sheet in workbook.findall(f".//{{{SPREADSHEET_NS}}}sheet")
        ]
        self.assertEqual(names, ["Event Timeline", "Device Information", "Master Schedule", "Commodity Summary"])


if __name__ == "__main__":
    unittest.main()
