import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from software.schedule_compiler import compile_cta_schedule, parse_test_start


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

            self.assertEqual(len(events), 8)
            machine_lines = machine_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(machine_lines[0], "# time,command,argument")
            self.assertEqual(machine_lines[1], "1784746785,o,")
            self.assertEqual(machine_lines[2], "1784746800,l,255")

            with preview_path.open("r", encoding="utf-8", newline="") as handle:
                preview = list(csv.DictReader(handle))
            self.assertEqual(preview[0]["offset_seconds"], "-15")
            self.assertEqual(preview[0]["scheduled_utc"], "2026-07-22T18:59:45Z")
            self.assertEqual(preview[1]["duration_byte"], "255")


if __name__ == "__main__":
    unittest.main()
