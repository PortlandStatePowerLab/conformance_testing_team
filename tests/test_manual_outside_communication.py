import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from software.gui.schedule_gui import save_schedule, load_schedule_rows
from software.scheduling.schedule_compiler import compile_cta_schedule
from software.scheduling.schedule_parser import (
    ScheduleValidationError, generate_cta_events, load_schedule,
)


def rows(second_command="load_up", automatic=False):
    commands = [("00:00:00", "outside_communication"),
                ("00:00:15", "load_up"), ("00:13:00", second_command),
                ("00:20:00", "end")]
    return [dict(enabled="TRUE", time_after_start=time, action=action,
                 event_duration_minutes="60" if action in {"load_up", "shed"} else "",
                 automatic_outside_communication=str(automatic).upper())
            for time, action in commands]


class ManualOutsideCommunicationTests(unittest.TestCase):
    def test_manual_schedules_compile_only_explicit_messages(self):
        for second_command in ("load_up", "shed", "outside_communication"):
            with self.subTest(second_command=second_command), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                schedule, summary = save_schedule(directory, "manual", rows(second_command))
                self.assertFalse(summary["automatic_outside_communication"])
                reopened = load_schedule_rows(schedule)
                self.assertTrue(all(row["automatic_outside_communication"] == "FALSE" for row in reopened))
                generated = compile_cta_schedule(
                    schedule, test_start=datetime(2026, 10, 29, tzinfo=timezone.utc),
                    controller_output=directory / "controller.csv",
                    preview_output=directory / "preview.csv",
                )
                self.assertEqual([(e.offset_seconds, e.action) for e in generated],
                                 [(0, "outside_communication"), (15, "load_up"), (780, second_command)])
                self.assertTrue(all(not e.generated for e in generated))
                machine = list(csv.DictReader((directory / "controller.csv").read_text().splitlines()[1:],
                                             fieldnames=("time", "command", "argument", "event_id", "value", "units", "efficiency")))
                self.assertEqual(machine[0]["command"], "o")
                self.assertEqual(machine[1]["command"], "l")

    def test_automatic_rejects_manual_outside_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ScheduleValidationError, "Manual Outside Communication"):
                save_schedule(Path(temp), "invalid", rows(automatic=True))

    def test_mode_must_be_consistent(self):
        mixed = rows()
        mixed[-1]["automatic_outside_communication"] = "TRUE"
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ScheduleValidationError, "same on every"):
                save_schedule(Path(temp), "invalid", mixed)

    def test_legacy_schedule_retains_automatic_prerequisites_and_heartbeats(self):
        legacy = rows()[1:]
        for row in legacy:
            row.pop("automatic_outside_communication")
        with tempfile.TemporaryDirectory() as temp:
            schedule, summary = save_schedule(Path(temp), "legacy", legacy)
            self.assertTrue(summary["automatic_outside_communication"])
            events = generate_cta_events(load_schedule(schedule))
            self.assertTrue(any(e.event_id.startswith("auto_outside_comm_heartbeat_") for e in events))
            self.assertTrue(any(e.prerequisite_for == "load_up_1" and e.offset_seconds == 0 for e in events))


if __name__ == "__main__":
    unittest.main()
