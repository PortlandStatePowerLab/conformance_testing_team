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
        self.assertEqual(rows[0]["event_id"], "load_up_1")
        self.assertEqual(rows[0]["event_type"], "cta")
        self.assertEqual(rows[0]["expected_operational_states"], "3|6")
        self.assertEqual(rows[0]["time_after_start"], "00:00:00")
        self.assertEqual(rows[-1]["event_id"], "test_end")
        self.assertEqual(rows[-1]["event_type"], "test")

    def test_generated_csv_passes_schedule_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "canonical.csv"
            import_xlsx_schedule(WORKBOOK, destination)
            events = load_schedule(destination)
        self.assertEqual(len(events), 9)
        self.assertEqual(events[-1].event_id, "test_end")


if __name__ == "__main__":
    unittest.main()
