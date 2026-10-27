import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software.station.equipment_metadata import (
    equipment_title_line, load_run_equipment, generate_public_equipment, public_equipment_record,
)


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


    def test_legacy_snapshot_uses_configured_display_name_without_rewriting_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "WH-1" / "example"
            equipment = root / "equipment"
            run.mkdir(parents=True)
            equipment.mkdir()
            snapshot = run / "equipment.json"
            original = json.dumps({"station_id": "WH-station1", "manufacturer": "Old Make"})
            snapshot.write_text(original)
            (equipment / "WH-station1.json").write_text(json.dumps({
                "equipment_id": "wh_current", "display_name": "HPWH-D"}))
            with patch("software.station.equipment_metadata.EQUIPMENT_DIRECTORY", equipment):
                self.assertEqual(equipment_title_line(run), "HPWH-D")
                snapshot.write_text(json.dumps({"equipment_id": "wh_other"}))
                self.assertEqual(equipment_title_line(run), "HPWH-1")
                snapshot.write_text(original)
            self.assertEqual(snapshot.read_text(), original)

    def test_public_record_refreshes_from_private_without_changing_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private" / "equipment" / "WH-station2.json"
            source.parent.mkdir(parents=True)
            public = root / "equipment"
            private = {
                "equipment_id": "wh_stable2", "display_name": "HPWH-2",
                "date_added": "2026-08-20", "capacity_gallons": 50,
                "temperature_setpoint_f": 125, "manufacturer": "Private make",
                "model_number": "Private model", "year": 2000,
                "future_private_field": "private",
            }
            original = json.dumps(private)
            source.write_text(original, encoding="utf-8")
            result = generate_public_equipment(source, public)
            self.assertEqual(source.read_text(), original)
            self.assertEqual(set(result), {"equipment_id", "display_name", "date_added",
                                           "capacity_gallons", "temperature_setpoint_f"})
            self.assertEqual(json.loads((public / source.name).read_text()), result)
            private["temperature_setpoint_f"] = 130
            source.write_text(json.dumps(private), encoding="utf-8")
            result = generate_public_equipment(source, public)
            self.assertEqual(result["temperature_setpoint_f"], 130)
            self.assertEqual(result["equipment_id"], "wh_stable2")
            self.assertEqual(list(public.glob("*.tmp")), [])

    def test_missing_or_invalid_public_fields_are_rejected(self):
        record = {"equipment_id": "wh_1", "display_name": "HPWH-1",
                  "date_added": "2026-08-20", "capacity_gallons": 50,
                  "temperature_setpoint_f": 125}
        with self.assertRaises(ValueError):
            public_equipment_record({k: v for k, v in record.items() if k != "equipment_id"})
        for value in (True, float("nan"), "125"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_equipment_record(dict(record, temperature_setpoint_f=value))

    def test_operational_defaults_use_private_records_and_plots_use_public(self):
        from software import conformance_test_runner as runner
        from software.gui import schedule_gui
        from software.station import equipment_metadata, hardware_preflight
        from software.sensors import water_temp_calibration_loader as water
        from software.calibration_tools import (
            hot_water_temp_calibration, cold_water_temp_calibration,
            flow_rate_calibration, power_calibration,
        )
        from software.monitoring import wh_power_monitor
        saved = Path(runner.__file__).resolve().parents[1] / "saved_data"
        self.assertEqual(runner.DEFAULT_EQUIPMENT_DIRECTORY, saved / "private" / "equipment")
        self.assertEqual(schedule_gui.DEFAULT_EQUIPMENT_DIRECTORY, saved / "private" / "equipment")
        self.assertEqual(equipment_metadata.EQUIPMENT_DIRECTORY, saved / "equipment")
        for module in (runner, water, hot_water_temp_calibration, cold_water_temp_calibration,
                       flow_rate_calibration, power_calibration):
            self.assertEqual(module.DEFAULT_CALIBRATION_DIRECTORY, saved / "calibration")
        self.assertEqual(hardware_preflight.build_parser().parse_args([]).power_configuration_dir,
                         saved / "calibration")
        self.assertEqual(wh_power_monitor.build_parser().parse_args([]).calibration_dir,
                         saved / "calibration")


if __name__ == "__main__":
    unittest.main()
