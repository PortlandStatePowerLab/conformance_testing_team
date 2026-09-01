import csv
import tempfile
import unittest
from pathlib import Path

from software.schedule_parser import (
    CUT_IN_RECOVERY_TIMEOUT_SECONDS,
    EXTENDED_SCHEDULE_COLUMNS,
    DRAW_EXTENDED_SCHEDULE_COLUMNS,
    SCHEDULE_COLUMNS,
    ScheduleValidationError,
    encode_event_duration,
    generate_cta_events,
    load_schedule,
)
from software.cta_operational_states import (
    EXPECTED_STATES_BY_ACTION,
    operational_state_name,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


class DurationEncodingTests(unittest.TestCase):
    def test_special_duration_values(self):
        self.assertEqual(encode_event_duration("max").byte_value, 0x00)

    def test_finite_duration_rounds_up(self):
        duration = encode_event_duration("90")
        self.assertEqual(duration.byte_value, 52)
        self.assertEqual(duration.requested_seconds, 5400)
        self.assertEqual(duration.represented_seconds, 5408)

    def test_sixty_minutes_encodes_as_byte_43(self):
        duration = encode_event_duration("60")
        self.assertEqual(duration.byte_value, 43)
        self.assertEqual(duration.requested_seconds, 3600)
        self.assertEqual(duration.represented_seconds, 3698)

    def test_duration_must_be_minutes_or_max(self):
        for invalid in ("01:00:00", "unknown", "0", "2151"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "1 to 2150"):
                    encode_event_duration(invalid)

    def test_operational_state_mapping(self):
        self.assertEqual(operational_state_name(4), "Idle Curtailed")
        self.assertEqual(EXPECTED_STATES_BY_ACTION["run_normal"], (0, 1))
        self.assertEqual(EXPECTED_STATES_BY_ACTION["shed"], (2, 4))


class MasterScheduleTests(unittest.TestCase):
    def test_cut_in_and_dependent_temp_drop_schedule_is_valid(self):
        rows = [
            ["true", "shed_1", "00:00:00", "pre_event", "", "cta", "shed", "max", "", "", "2|4", "", "", "", "", "", ""],
            ["true", "water_draw_1", "TBD", "pre_event", "Cut-in", "water_draw", "water_draw", "", "", "", "", "", "", "", "30", "", ""],
            ["true", "water_draw_2", "TBD", "event", "Temp Drop", "water_draw", "water_draw", "", "", "", "", "", "", "15", "60", "", ""],
            ["true", "test_end", "TBD", "event", "", "test", "end", "", "", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(DRAW_EXTENDED_SCHEDULE_COLUMNS)
                writer.writerows(rows)
            events = load_schedule(path)

        cut_in = next(event for event in events if event.draw_type == "cut-in")
        temp_drop = next(event for event in events if event.draw_type == "temp drop")
        self.assertTrue(cut_in.dependent_end)
        self.assertEqual(cut_in.offset_seconds, 0)
        self.assertEqual(cut_in.expected_draw_seconds, 30 * 60)
        self.assertEqual(CUT_IN_RECOVERY_TIMEOUT_SECONDS, 12 * 60 * 60)
        self.assertEqual(
            temp_drop.offset_seconds,
            30 * 60 + CUT_IN_RECOVERY_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            events[-1].offset_seconds,
            90 * 60 + CUT_IN_RECOVERY_TIMEOUT_SECONDS,
        )

    def test_volume_cannot_follow_state_controlled_draw(self):
        rows = [
            ["true", "shed_1", "00:00:00", "pre_event", "", "cta", "shed", "max", "", "", "2|4", "", "", "", "", "", ""],
            ["true", "water_draw_1", "TBD", "pre_event", "Cut-in", "water_draw", "water_draw", "", "", "", "", "", "", "", "30", "", ""],
            ["true", "water_draw_2", "01:00:00", "event", "Volume", "water_draw", "water_draw", "", "", "", "", "5", "3", "", "", "", ""],
            ["true", "test_end", "02:00:00", "event", "", "test", "end", "", "", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(DRAW_EXTENDED_SCHEDULE_COLUMNS)
                writer.writerows(rows)
            with self.assertRaisesRegex(ScheduleValidationError, "Volume draws cannot follow"):
                load_schedule(path)

    def test_tbd_temp_drop_requires_immediately_preceding_cut_in(self):
        rows = [
            ["true", "water_draw_1", "00:10:00", "event", "Volume", "water_draw", "water_draw", "", "", "", "", "2", "3", "", "", "", ""],
            ["true", "water_draw_2", "TBD", "event", "Temp Drop", "water_draw", "water_draw", "", "", "", "", "", "", "15", "60", "", ""],
            ["true", "test_end", "02:00:00", "event", "", "test", "end", "", "", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(DRAW_EXTENDED_SCHEDULE_COLUMNS)
                writer.writerows(rows)
            with self.assertRaisesRegex(ScheduleValidationError, "only immediately after Cut-in"):
                load_schedule(path)

    def test_temp_drop_draw_allows_dependent_tbd_end(self):
        rows = [
            ["true", "water_draw_1", "01:35:00", "event", "Temp Drop", "water_draw", "water_draw", "", "", "", "", "", "", "15", "60", "", ""],
            ["true", "test_end", "TBD", "event", "", "test", "end", "", "", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(DRAW_EXTENDED_SCHEDULE_COLUMNS)
                writer.writerows(rows)
            events = load_schedule(path)
        self.assertEqual(events[0].draw_type, "temp drop")
        self.assertTrue(events[-1].dependent_end)
        self.assertEqual(events[-1].offset_seconds, 2 * 3600 + 35 * 60)

    def test_tbd_end_is_rejected_for_volume_draw(self):
        rows = [
            ["true", "water_draw_1", "01:35:00", "event", "Volume", "water_draw", "water_draw", "", "", "", "", "2", "3", "", "", "", ""],
            ["true", "test_end", "TBD", "event", "", "test", "end", "", "", "", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(DRAW_EXTENDED_SCHEDULE_COLUMNS)
                writer.writerows(rows)
            with self.assertRaisesRegex(ScheduleValidationError, "Temp Drop"):
                load_schedule(path)

    def test_checked_in_schedule_is_valid(self):
        events = load_schedule(MASTER_SCHEDULE)
        self.assertEqual(events[-1].event_id, "test_end")

    def test_outside_communication_is_generated_fifteen_seconds_early(self):
        events = load_schedule(MASTER_SCHEDULE)
        generated = generate_cta_events(events)
        first_cta = next(event for event in events if event.event_type == "cta")
        first = generated[0]
        self.assertEqual(
            first.event_id, f"auto_outside_comm_for_{first_cta.event_id}"
        )
        self.assertEqual(first.offset_seconds, first_cta.offset_seconds - 15)
        self.assertEqual(first.command_code, "o")

    def test_overlapping_draws_are_rejected(self):
        rows = [
            ["true", "water_draw_1", "00:00:00", "event", "water_draw", "water_draw", "", "", "", "", "15", "3", ""],
            ["true", "water_draw_2", "00:04:00", "event", "water_draw", "water_draw", "", "", "", "", "1", "3", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)
            with self.assertRaisesRegex(ScheduleValidationError, "overlap"):
                load_schedule(path)

    def test_advanced_load_up_arguments_are_parsed(self):
        rows = [
            ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "60", "5", "100_wh", "3|6", "", "", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)
            event = load_schedule(path)[0]
        self.assertEqual(event.advanced_duration_minutes, 60)
        self.assertEqual(event.advanced_value, 5)
        self.assertEqual(event.advanced_units, 0x02)
        self.assertEqual(event.expected_operational_states, (3, 6))

    def test_advanced_load_up_max_duration_uses_unsigned_16_bit_maximum(self):
        rows = [
            ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "max", "5", "100_wh", "3|6", "", "", ""],
            ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(SCHEDULE_COLUMNS)
                writer.writerows(rows)
            event = load_schedule(path)[0]
        self.assertEqual(event.advanced_duration_minutes, 0xFFFF)

    def test_optional_advanced_efficiency_accepts_zero_through_ten(self):
        for efficiency in ("0", "5", "10"):
            with self.subTest(efficiency=efficiency), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "schedule.csv"
                rows = [
                    ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "60", "5", "100_wh", "3|6", "", "", "", efficiency],
                    ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", "", ""],
                ]
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(EXTENDED_SCHEDULE_COLUMNS)
                    writer.writerows(rows)

                event = load_schedule(path)[0]

                self.assertEqual(event.advanced_efficiency, int(efficiency))

    def test_reserved_advanced_efficiency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            rows = [
                ["true", "advanced_1", "00:00:00", "event", "cta", "advanced_load_up", "60", "5", "100_wh", "3|6", "", "", "", "11"],
                ["true", "test_end", "01:00:00", "event", "test", "end", "", "", "", "", "", "", "", ""],
            ]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(EXTENDED_SCHEDULE_COLUMNS)
                writer.writerows(rows)

            with self.assertRaisesRegex(ScheduleValidationError, "between 0 and 10"):
                load_schedule(path)

    def test_empty_trailing_spreadsheet_column_is_accepted(self):
        expected_count = len(load_schedule(MASTER_SCHEDULE))
        with MASTER_SCHEDULE.open("r", encoding="utf-8", newline="") as source:
            lines = source.read().splitlines()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            path.write_text(
                "\n".join(line + "," for line in lines) + "\n",
                encoding="utf-8",
            )
            events = load_schedule(path)
        self.assertEqual(len(events), expected_count)

    def test_nonempty_trailing_column_is_rejected(self):
        with MASTER_SCHEDULE.open("r", encoding="utf-8", newline="") as source:
            lines = source.read().splitlines()
        lines[0] += ","
        lines[1] += ",unexpected"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ScheduleValidationError, "unexpected trailing column data"
            ):
                load_schedule(path)


if __name__ == "__main__":
    unittest.main()
