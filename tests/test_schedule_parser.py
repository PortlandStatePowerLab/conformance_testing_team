import csv
import tempfile
import unittest
from pathlib import Path

from software.schedule_parser import (
    LONG_DURATION,
    SCHEDULE_COLUMNS,
    ScheduleValidationError,
    encode_event_duration,
    generate_cta_events,
    load_schedule,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class DurationEncodingTests(unittest.TestCase):
    def test_special_duration_values(self):
        self.assertEqual(encode_event_duration("unknown").byte_value, 0x00)
        self.assertEqual(encode_event_duration(LONG_DURATION).byte_value, 0xFF)

    def test_finite_duration_rounds_up(self):
        duration = encode_event_duration("01:30:00")
        self.assertEqual(duration.byte_value, 52)
        self.assertEqual(duration.requested_seconds, 5400)
        self.assertEqual(duration.represented_seconds, 5408)


class MasterScheduleTests(unittest.TestCase):
    def test_checked_in_schedule_is_valid(self):
        events = load_schedule(MASTER_SCHEDULE)
        self.assertEqual(len(events), 8)
        self.assertEqual(events[-1].event_id, "test_end")

    def test_outside_communication_is_generated_fifteen_seconds_early(self):
        events = load_schedule(MASTER_SCHEDULE)
        generated = generate_cta_events(events)
        first = generated[0]
        self.assertEqual(first.event_id, "auto_outside_comm_for_cta_loadup_1")
        self.assertEqual(first.offset_seconds, -15)
        self.assertEqual(first.command_code, "o")
        load_up = next(event for event in generated if event.event_id == "cta_loadup_1")
        self.assertEqual(load_up.duration_byte, 0xFF)

    def test_overlapping_draws_are_rejected(self):
        rows = [
            ["true", "draw_1", "00:00:00", "event", "water_draw", "draw", "", "15", "3", ""],
            ["true", "draw_2", "00:04:00", "event", "water_draw", "draw", "", "1", "3", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)
            with self.assertRaisesRegex(ScheduleValidationError, "overlap"):
                load_schedule(path)


if __name__ == "__main__":
    unittest.main()
