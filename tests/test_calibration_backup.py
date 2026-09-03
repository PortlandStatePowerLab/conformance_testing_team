import tempfile
import unittest
from pathlib import Path

from software.calibration_backup import replace_station_backup


class CalibrationBackupTests(unittest.TestCase):
    def test_replaces_only_backups_for_the_selected_station(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            calibration = folder / "WH-station1.json"
            calibration.write_text('{"version":2}', encoding="utf-8")
            old_same_station = folder / "WH-station1_old.json.save"
            old_same_station.write_text('{"version":1}', encoding="utf-8")
            other_station = folder / "WH-station2_old.json.save"
            other_station.write_text('{"station":2}', encoding="utf-8")
            new_backup = folder / "WH-station1_new.json.save"

            replace_station_backup(calibration, new_backup)

            self.assertFalse(old_same_station.exists())
            self.assertEqual(new_backup.read_text(encoding="utf-8"), '{"version":2}')
            self.assertEqual(
                other_station.read_text(encoding="utf-8"), '{"station":2}'
            )


if __name__ == "__main__":
    unittest.main()
