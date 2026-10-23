import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software.station.equipment_metadata import equipment_title_line, load_run_equipment


class EquipmentMetadataTests(unittest.TestCase):
    def test_prefers_archived_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "WH-3" / "example"
            run.mkdir(parents=True)
            (run / "equipment.json").write_text(
                json.dumps({
                    "display_name": "HPWH-3",
                    "equipment_id": "wh_archived3",
                }),
                encoding="utf-8",
            )
            self.assertEqual(equipment_title_line(run), "HPWH-3")

    def test_falls_back_to_station_file_for_older_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "WH-4" / "example"
            equipment = root / "equipment"
            run.mkdir(parents=True)
            equipment.mkdir()
            (equipment / "WH-station4.json").write_text(
                json.dumps({
                    "station_id": "WH-station4",
                    "manufacturer": "Current Make",
                    "model_number": "NOW-4",
                }),
                encoding="utf-8",
            )
            with patch("software.station.equipment_metadata.EQUIPMENT_DIRECTORY", equipment):
                number, value = load_run_equipment(run)
                self.assertEqual(equipment_title_line(run), "HPWH-4")
            self.assertEqual(number, 4)
            self.assertEqual(value["model_number"], "NOW-4")


if __name__ == "__main__":
    unittest.main()
