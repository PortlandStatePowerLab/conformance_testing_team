"""Schedule validation for recovery-dependent draw sequences."""

import csv
import tempfile
import unittest
from pathlib import Path

from software.scheduling.schedule_parser import (
    DRAW_EXTENDED_SCHEDULE_COLUMNS, ScheduleValidationError, load_schedule,
)


class DrawSequenceTests(unittest.TestCase):
    def load(self, draws, end="TBD"):
        rows = [dict(enabled="TRUE", event_id="normal", time_after_start="00:00:00",
                     event_type="cta", action="run_normal", event_duration_minutes="max")]
        for index, (kind, start) in enumerate(draws):
            row = dict(enabled="TRUE", event_id=f"draw_{index}", time_after_start=start,
                       event_type="water_draw", action="water_draw", draw_type=kind)
            if kind == "Volume":
                row.update(target_volume_gal="5", expected_flow_gpm="3")
            else:
                row["max_draw_minutes"] = "60"
                if kind == "Temp Drop":
                    row["temp_drop_f"] = "15"
            rows.append(row)
        rows.append(dict(enabled="TRUE", event_id="end", time_after_start=end,
                         event_type="test", action="end"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=DRAW_EXTENDED_SCHEDULE_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            return load_schedule(path)

    def test_supported_recovery_sequences(self):
        for kinds in (
            ("Temp Drop", "Temp Drop", "Temp Drop"),
            ("Temp Drop", "Volume"),
            ("Cut-in", "Volume"),
            ("Cut-in", "Temp Drop", "Volume"),
            ("Volume", "Temp Drop", "Volume"),
        ):
            with self.subTest(kinds=kinds):
                starts = ["TBD" if kinds[0] == "Cut-in" else "00:10:00"] + ["TBD"] * (len(kinds) - 1)
                events = self.load(zip(kinds, starts))
                draws = [event for event in events if event.event_type == "water_draw"]
                self.assertEqual([event.draw_type for event in draws], [kind.lower() for kind in kinds])
                self.assertTrue(all(event.dependent_end for event in draws[1:]))
                self.assertTrue(events[-1].dependent_end)

    def test_cut_in_cannot_follow_another_draw(self):
        with self.assertRaisesRegex(ScheduleValidationError, "only as the first"):
            self.load([("Temp Drop", "00:10:00"), ("Cut-in", "TBD"), ("Volume", "TBD")])

    def test_subsequent_draws_cannot_use_fixed_times_after_temp_drop(self):
        for kind in ("Temp Drop", "Volume"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ScheduleValidationError, "must use TBD"):
                self.load([("Temp Drop", "00:10:00"), (kind, "01:30:00")])

    def test_first_draw_cannot_be_tbd_unless_cut_in(self):
        for kind in ("Temp Drop", "Volume"):
            with self.subTest(kind=kind), self.assertRaises(ScheduleValidationError):
                self.load([(kind, "TBD")])

    def test_fixed_volume_sequence_is_unchanged(self):
        events = self.load([("Volume", "00:10:00"), ("Volume", "00:20:00")], end="01:00:00")
        self.assertFalse(events[-1].dependent_end)
