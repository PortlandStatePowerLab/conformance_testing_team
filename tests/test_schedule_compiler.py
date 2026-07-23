import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from software.schedule_compiler import compile_cta_schedule, parse_test_start
from software.schedule_parser import SCHEDULE_COLUMNS, load_schedule


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class ScheduleCompilerTests(unittest.TestCase):
    def test_test_start_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            parse_test_start("2026-07-22T12:00:00")

    def test_compiler_writes_machine_and_preview_schedules(self):
        test_start = datetime(2026, 7, 22, 19, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            machine_path = output_directory / "schedule.csv"
            preview_path = output_directory / "cta_schedule_preview.csv"
            events = compile_cta_schedule(
                MASTER_SCHEDULE,
                test_start=test_start,
                controller_output=machine_path,
                preview_output=preview_path,
            )

            expected_cta_events = sum(
                event.event_type == "cta" for event in load_schedule(MASTER_SCHEDULE)
            ) * 2
            self.assertEqual(len(events), expected_cta_events)
            machine_lines = machine_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                machine_lines[0],
                "# time,command,argument,event_id,value,units",
            )
            self.assertEqual(
                machine_lines[1],
                "1784746785,o,,auto_outside_comm_for_load_up_1,,",
            )
            self.assertEqual(machine_lines[2], "1784746800,l,13,load_up_1,,")

            with preview_path.open("r", encoding="utf-8", newline="") as handle:
                preview = list(csv.DictReader(handle))
            self.assertEqual(preview[0]["offset_seconds"], "-15")
            self.assertEqual(preview[0]["scheduled_utc"], "2026-07-22T18:59:45Z")
            self.assertEqual(preview[1]["duration_byte"], "13")
            self.assertEqual(preview[1]["requested_duration_seconds"], "300")
            self.assertEqual(preview[1]["represented_duration_seconds"], "338")

    def test_advanced_load_up_is_compiled_with_all_three_arguments(self):
        rows = [
            ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "", "60", "5", "100_wh", "3|6", "", "", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            master_path = output_directory / "master.csv"
            with master_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)

            machine_path = output_directory / "schedule.csv"
            preview_path = output_directory / "preview.csv"
            compile_cta_schedule(
                master_path,
                test_start=datetime(2026, 7, 22, 19, 0, 0, tzinfo=timezone.utc),
                controller_output=machine_path,
                preview_output=preview_path,
            )
            machine_lines = machine_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(machine_lines[2], "1784746800,a,60,advanced_1,5,2")
            with preview_path.open("r", encoding="utf-8", newline="") as handle:
                preview = list(csv.DictReader(handle))
            self.assertEqual(preview[1]["expected_operational_states"], "3|6")


if __name__ == "__main__":
    unittest.main()
