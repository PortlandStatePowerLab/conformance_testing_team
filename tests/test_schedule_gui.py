import csv
import tempfile
import unittest
from pathlib import Path

from software.schedule_gui import (
    derive_rows,
    editor_metadata,
    load_schedule_rows,
    normalize_schedule_name,
    save_schedule,
    validate_rows,
)
from software.schedule_parser import ScheduleValidationError, load_schedule


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCHEDULE = REPOSITORY_ROOT / "software" / "conformance_test_schedule.csv"


def master_rows():
    with MASTER_SCHEDULE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ScheduleGuiTests(unittest.TestCase):
    def test_metadata_comes_from_existing_python_definitions(self):
        metadata = editor_metadata()
        actions = {item["action"]: item for item in metadata["actions"]}

        self.assertEqual(actions["load_up"]["event_type"], "cta")
        self.assertEqual(actions["load_up"]["expected_operational_states"], [3, 6])
        self.assertEqual(
            actions["water_draw"]["fields"],
            ["target_volume_gal", "expected_flow_gpm"],
        )
        self.assertIn("100_wh", metadata["advanced_units"])
        self.assertEqual(
            [item["value"] for item in metadata["advanced_efficiencies"]],
            list(range(11)),
        )

    def test_technical_fields_are_derived_from_action(self):
        source = master_rows()
        for row in source:
            row["event_id"] = "browser value is ignored"
            row["event_type"] = "browser value is ignored"
            row["expected_operational_states"] = "255"

        derived = derive_rows(source)

        self.assertEqual(derived[0]["event_id"], "load_up_1")
        self.assertEqual(derived[0]["event_type"], "cta")
        self.assertEqual(derived[0]["expected_operational_states"], "3|6")
        self.assertEqual(derived[-1]["event_id"], "test_end")
        self.assertEqual(derived[-1]["event_type"], "test")

    def test_existing_canonical_rows_validate_without_gui_rules(self):
        rows, summary = validate_rows(master_rows())

        self.assertEqual(len(rows), summary["enabled_events"])
        self.assertGreater(summary["cta_events"], 0)
        self.assertGreater(summary["water_draws"], 0)

    def test_save_is_canonical_and_loadable_by_existing_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            destination, summary = save_schedule(
                Path(directory), "gui_test", master_rows()
            )

            events = load_schedule(destination)
            loaded_rows = load_schedule_rows(destination)

        self.assertEqual(destination.name, "gui_test.csv")
        self.assertEqual(len(events), summary["enabled_events"])
        self.assertEqual(
            [
                {key: row[key] for key in master_rows()[0]}
                for row in loaded_rows
            ],
            master_rows(),
        )
        self.assertTrue(
            all(row["advanced_efficiency"] == "" for row in loaded_rows)
        )

    def test_invalid_update_does_not_overwrite_valid_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule_directory = Path(directory)
            destination, _ = save_schedule(
                schedule_directory, "protected", master_rows()
            )
            original = destination.read_bytes()
            invalid_rows = master_rows()
            invalid_rows[-1]["enabled"] = "FALSE"

            with self.assertRaises(ScheduleValidationError):
                save_schedule(schedule_directory, "protected", invalid_rows)

            self.assertEqual(destination.read_bytes(), original)

    def test_schedule_name_cannot_escape_schedule_directory(self):
        for invalid in ("../outside", "nested/name", "", ".hidden", "name.csv.exe"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_schedule_name(invalid)

        self.assertEqual(normalize_schedule_name("test-one.csv"), "test-one.csv")

    def test_unknown_browser_fields_are_rejected(self):
        rows = master_rows()
        rows[0]["unexpected"] = "value"

        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_rows(rows)

    def test_efficiency_zero_survives_gui_save_and_reload(self):
        rows = [
            {
                "enabled": "TRUE",
                "event_id": "ignored",
                "time_after_start": "00:00:00",
                "phase": "event",
                "event_type": "cta",
                "action": "advanced_load_up",
                "event_duration_minutes": "60",
                "advanced_value": "5",
                "advanced_units": "100_wh",
                "expected_operational_states": "",
                "target_volume_gal": "",
                "expected_flow_gpm": "",
                "notes": "",
                "advanced_efficiency": "0",
            },
            {
                "enabled": "TRUE",
                "event_id": "ignored",
                "time_after_start": "01:00:00",
                "phase": "",
                "event_type": "test",
                "action": "end",
                "event_duration_minutes": "",
                "advanced_value": "",
                "advanced_units": "",
                "expected_operational_states": "",
                "target_volume_gal": "",
                "expected_flow_gpm": "",
                "notes": "",
                "advanced_efficiency": "",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            destination, _ = save_schedule(Path(directory), "efficiency_zero", rows)
            loaded = load_schedule_rows(destination)
            event = load_schedule(destination)[0]

        self.assertEqual(loaded[0]["advanced_efficiency"], "0")
        self.assertEqual(event.advanced_efficiency, 0)


if __name__ == "__main__":
    unittest.main()
