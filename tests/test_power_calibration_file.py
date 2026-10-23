import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from software.helpers.helper_power_functions import (
    get_calibration_from_JSON,
    set_calibration,
)


POWER = {
    "equipment_id": "wh_example",
    "vrms_scale": 0.01,
    "irms_scale": 0.002,
    "vrms_offset": 10,
    "irms_offset": 20,
    "vrms_offset_volts": 0.1,
    "irms_offset_amps": 0.04,
    "last_cal_time": "2026-09-01T12:00:00",
    "line_vrms_used": 240.0,
    "clamp_irms_used": 20.0,
}


class PowerCalibrationFileTests(unittest.TestCase):
    def test_nested_power_section_is_loaded_without_hot_section(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration_dir = Path(directory)
            (calibration_dir / "WH-station3.json").write_text(
                json.dumps(
                    {
                        "power": POWER,
                        "hot_water_temp": {"correction_offset_f": 3.325},
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "software.helpers.helper_power_functions.socket.gethostname",
                return_value="WH-station3",
            ):
                loaded = get_calibration_from_JSON(str(calibration_dir), directory)

        self.assertEqual(loaded["vrms_scale"], POWER["vrms_scale"])
        self.assertNotIn("hot_water_temp", loaded)

    def test_legacy_flat_power_file_remains_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration_dir = Path(directory)
            (calibration_dir / "WH-station2.json").write_text(
                json.dumps(POWER), encoding="utf-8"
            )
            with patch(
                "software.helpers.helper_power_functions.socket.gethostname",
                return_value="WH-station2",
            ):
                loaded = get_calibration_from_JSON(str(calibration_dir), directory)

        self.assertEqual(loaded["irms_offset"], 20)

    def test_save_replaces_only_power_and_uses_equipment_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            saved_data = Path(directory)
            calibration_dir = saved_data / "calibration"
            equipment_dir = saved_data / "equipment"
            calibration_dir.mkdir()
            equipment_dir.mkdir()
            path = calibration_dir / "WH-station4.json"
            hot = {"correction_offset_f": 2.133}
            path.write_text(
                json.dumps({"power": POWER, "hot_water_temp": hot}),
                encoding="utf-8",
            )
            (equipment_dir / "WH-station4.json").write_text(
                json.dumps(
                    {
                        "equipment_id": "wh_equipment4",
                    }
                ),
                encoding="utf-8",
            )
            updated_power = dict(POWER, vrms_scale=0.02)

            set_calibration(
                updated_power,
                str(calibration_dir),
                str(saved_data),
                hostname="WH-station4",
            )

            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["hot_water_temp"], hot)
            self.assertEqual(updated["power"]["vrms_scale"], 0.02)
            self.assertEqual(updated["power"]["equipment_id"], "wh_equipment4")
            self.assertEqual(updated["equipment_id"], "wh_equipment4")
            self.assertNotIn("manufacturer", updated["power"])
            self.assertNotIn("model_number", updated["power"])
            backups = list(calibration_dir.glob("WH-station4_*.json.save"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                json.loads(backups[0].read_text(encoding="utf-8"))["hot_water_temp"],
                hot,
            )

    def test_partial_power_update_preserves_all_sensor_and_unrelated_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station1.json"
            sensor = {"manufacturer": "Sensor Make", "model_number": "Sensor Model",
                      "serial_number": "sensor-123", "range": [0, 30]}
            original = {
                "equipment_id": "wh_existing", "display_name": "HPWH-1",
                "notes": {"station": "keep me"}, "last_cal_time": "station-level date",
                "power": dict(POWER, sensor=sensor, sensor_manufacturer="Power Sensor Make",
                              sensor_model_number="Power Sensor Model", custom_field={"keep": True}),
                "hot_water_temp": {"manufacturer": "Thermometer Make", "correction_offset_f": 1.5},
                "cold_water_temp": {"correction_offset_f": -1},
                "flow_rate": {"model_number": "Flow Sensor Model", "scale_gpm_per_count": .005},
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            set_calibration({"vrms_scale": .025, "last_cal_time": "new power date"},
                            directory, directory, hostname="WH-station1")
            actual = json.loads(path.read_text())
            expected = json.loads(json.dumps(original))
            expected["power"].update(vrms_scale=.025, last_cal_time="new power date")
            self.assertEqual(actual, expected)
            backup = next(Path(directory).glob("WH-station1_*.json.save"))
            self.assertEqual(json.loads(backup.read_text()), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_legacy_flat_record_migrates_coefficients_but_keeps_metadata_and_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station2.json"
            original = dict(POWER, notes="keep", sensor={"manufacturer": "Sensor Make"})
            path.write_text(json.dumps(original))
            set_calibration({"vrms_scale": .025}, directory, directory, hostname="WH-station2")
            actual = json.loads(path.read_text())
            self.assertEqual(actual["equipment_id"], original["equipment_id"])
            self.assertEqual(actual["notes"], "keep")
            self.assertEqual(actual["sensor"], original["sensor"])
            self.assertNotIn("vrms_scale", actual)
            self.assertEqual(actual["power"], dict(POWER, vrms_scale=.025))

    def test_legacy_heater_identity_is_removed_but_sensor_identity_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station3.json"
            original = {"manufacturer": "Heater Make", "model_number": "Heater Model",
                        "power": dict(POWER, manufacturer="Heater Make", model_number="Heater Model",
                                      sensor={"manufacturer": "Sensor Make", "model_number": "Sensor Model"})}
            path.write_text(json.dumps(original))
            set_calibration({"irms_scale": .003}, directory, directory, hostname="WH-station3")
            actual = json.loads(path.read_text())
            self.assertNotIn("manufacturer", actual)
            self.assertNotIn("model_number", actual["power"])
            self.assertEqual(actual["power"]["sensor"], original["power"]["sensor"])

    def test_malformed_power_section_is_rejected_without_changing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station1.json"
            original = '{"power": "invalid", "notes": "keep"}'
            path.write_text(original)
            with self.assertRaisesRegex(ValueError, "power calibration"):
                set_calibration(POWER, directory, directory, hostname="WH-station1")
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(Path(directory).glob("*.save")), [])


if __name__ == "__main__":
    unittest.main()
