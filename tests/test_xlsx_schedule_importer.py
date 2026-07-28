import tempfile
import unittest
from pathlib import Path

from software.schedule_parser import load_schedule
from software.xlsx_schedule_importer import import_xlsx_schedule, workbook_rows


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = REPOSITORY_ROOT / "software" / "conformance_test_schedule_main.xlsx"


class XlsxScheduleImporterTests(unittest.TestCase):
    def test_workbook_metadata_is_derived_from_action(self):
        rows = workbook_rows(WORKBOOK)
        self.assertGreater(len(rows), 0)
        for row in rows:
            if row["action"] == "end":
                self.assertEqual(row["event_type"], "test")
            elif row["action"] == "water_draw":
                self.assertEqual(row["event_type"], "water_draw")
            else:
                self.assertEqual(row["event_type"], "cta")

    def test_generated_csv_passes_schedule_validation(self):
        rows = workbook_rows(WORKBOOK)
        expected_enabled_events = sum(
            row["enabled"].strip().lower() in {"true", "1", "yes", "y"}
            for row in rows
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "canonical.csv"
            import_xlsx_schedule(WORKBOOK, destination)
            events = load_schedule(destination)
        self.assertEqual(len(events), expected_enabled_events)
        self.assertEqual(events[-1].event_id, "test_end")


if __name__ == "__main__":
    unittest.main()
