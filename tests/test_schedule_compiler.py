import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from software.schedule_compiler import compile_cta_schedule, parse_test_start
from software.schedule_parser import (
    EXTENDED_SCHEDULE_COLUMNS,
    SCHEDULE_COLUMNS,
    load_schedule,
)


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

            self.assertGreaterEqual(
                len(events),
                sum(
                    event.event_type == "cta"
                    for event in load_schedule(MASTER_SCHEDULE)
                )
                * 2,
            )
            machine_lines = machine_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                machine_lines[0],
                "# time,command,argument,event_id,value,units,efficiency",
            )
            first_cta = next(
                event
                for event in load_schedule(MASTER_SCHEDULE)
                if event.event_type == "cta"
            )
            self.assertEqual(
                machine_lines[1],
                f"{int(test_start.timestamp()) + first_cta.offset_seconds - 15},"
                f"o,,auto_outside_comm_for_{first_cta.event_id},,,",
            )

            with preview_path.open("r", encoding="utf-8", newline="") as handle:
                preview = list(csv.DictReader(handle))
            self.assertEqual(
                preview[0]["offset_seconds"],
                str(first_cta.offset_seconds - 15),
            )
            self.assertEqual(
                preview[0]["scheduled_pacific"],
                "2026-07-22T11:59:45-07:00",
            )

    def test_advanced_load_up_is_compiled_with_all_three_arguments(self):
        rows = [
            ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "60", "5", "100_wh", "3|6", "", "", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", ""],
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
            self.assertEqual(machine_lines[2], "1784746800,a,60,advanced_1,5,2,")
            with preview_path.open("r", encoding="utf-8", newline="") as handle:
                preview = list(csv.DictReader(handle))
            self.assertEqual(preview[1]["expected_operational_states"], "3|6")

    def test_advanced_efficiency_zero_is_compiled_as_present(self):
        rows = [
            ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "60", "5", "100_wh", "3|6", "", "", "", "0"],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            master_path = output_directory / "master.csv"
            with master_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(EXTENDED_SCHEDULE_COLUMNS)
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
            with preview_path.open("r", encoding="utf-8", newline="") as handle:
                preview = list(csv.DictReader(handle))

        self.assertEqual(machine_lines[2], "1784746800,a,60,advanced_1,5,2,0")
        self.assertEqual(preview[1]["advanced_efficiency"], "0")

    def test_outside_communication_heartbeat_continues_through_run_normal(self):
        rows = [
            ["true", "shed_1", "00:00:00", "event", "cta", "shed", "1", "", "", "4|5", "", "", ""],
            ["true", "normal_1", "00:30:00", "event", "cta", "run_normal", "unknown", "", "", "0|1", "", "", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            master_path = output_directory / "master.csv"
            with master_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)

            events = compile_cta_schedule(
                master_path,
                test_start=datetime(2026, 7, 22, 19, 0, 0, tzinfo=timezone.utc),
                controller_output=output_directory / "schedule.csv",
                preview_output=output_directory / "preview.csv",
            )

        heartbeats = [
            event
            for event in events
            if event.event_id.startswith("auto_outside_comm_heartbeat_")
        ]
        self.assertEqual(len(heartbeats), 4)
        self.assertEqual(
            [event.offset_seconds for event in heartbeats],
            [13 * 60 + 15, 26 * 60 + 45, 40 * 60 + 15, 53 * 60 + 45],
        )
        self.assertTrue(all(event.command_code == "o" for event in heartbeats))
        self.assertTrue(all(event.prerequisite_for is None for event in heartbeats))
        self.assertEqual(
            sum(event.action == "shed" for event in events),
            1,
        )
        self.assertTrue(
            any(event.offset_seconds > 30 * 60 for event in heartbeats)
        )

    def test_heartbeat_can_be_disabled_without_removing_prerequisites(self):
        rows = [
            ["true", "load_up_1", "00:00:00", "event", "cta", "load_up", "20", "", "", "3|6", "", "", ""],
            ["true", "normal_1", "00:25:00", "event", "cta", "run_normal", "unknown", "", "", "0|1", "", "", ""],
            ["true", "test_end", "00:27:00", "event", "test", "end", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            master_path = output_directory / "master.csv"
            with master_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)

            events = compile_cta_schedule(
                master_path,
                test_start=datetime(2026, 7, 22, 19, 0, 0, tzinfo=timezone.utc),
                controller_output=output_directory / "schedule.csv",
                preview_output=output_directory / "preview.csv",
                outside_communication_heartbeat_enabled=False,
            )

        self.assertFalse(
            any(
                event.event_id.startswith("auto_outside_comm_heartbeat_")
                for event in events
            )
        )
        prerequisites = [
            event for event in events if event.prerequisite_for is not None
        ]
        self.assertEqual(len(prerequisites), 2)
        self.assertEqual(
            [event.offset_seconds for event in prerequisites],
            [-15, 25 * 60 - 15],
        )


if __name__ == "__main__":
    unittest.main()
