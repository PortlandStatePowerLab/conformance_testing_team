import json
import tempfile
import unittest
from pathlib import Path

from software.conformance_test_runner import _archive_station_calibration
from software.station.calibration_metadata import public_calibration_snapshot, sanitize_station_calibration
from software.sensors.water_temp_calibration_loader import (
    load_hot_water_offset_f, load_cold_water_offset_f, load_flow_calibration,
)


class CalibrationMetadataTests(unittest.TestCase):
    def test_export_preserves_corrections_and_local_record_without_leaking_identity(self):
        calibration = {
            "manufacturer": "Private heater make", "serial_number": "private-serial",
            "future_private_section": {"notes": "private"},
            "power": {"manufacturer": "Private heater make", "model_number": "Private model",
                      "serial_number": "private-serial", "notes": "private",
                      "vrms_scale": 0.01, "irms_scale": 0.02,
                      "vrms_offset": 10, "irms_offset": 20, "last_cal_time": "2026-08-20"},
            "hot_water_temp": {"correction_offset_f": 2.133,
                               "thermometer_used": "Reference thermometer"},
            "cold_water_temp": {"correction_offset_f": -1.25},
            "flow_rate": {"scale_gpm_per_count": 0.005, "offset_gpm": -2.5,
                          "reference_device": "Reference flow meter"},
        }
        equipment = {"equipment_id": "wh_test4", "display_name": "HPWH-4"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, local = root / "run", root / "calibration"
            run.mkdir()
            local.mkdir()
            source = local / "WH-station4.json"
            original = json.dumps(calibration)
            source.write_text(original, encoding="utf-8")
            (run / "equipment.json").write_text(json.dumps(equipment), encoding="utf-8")
            archived = _archive_station_calibration(
                run, hostname="WH-station4", calibration_directory=local,
            )
            snapshot = json.loads(archived.read_text())
            self.assertEqual(source.read_text(), original)
            self.assertEqual(snapshot["equipment_id"], equipment["equipment_id"])
            self.assertEqual(snapshot["display_name"], "HPWH-4")
            self.assertNotIn("private", archived.read_text().lower())
            self.assertEqual(snapshot["power"], {k: v for k, v in calibration["power"].items()
                                               if k not in {"manufacturer", "model_number", "serial_number", "notes"}})
            for section in ("hot_water_temp", "cold_water_temp", "flow_rate"):
                self.assertEqual(snapshot[section], calibration[section])
            self.assertEqual(load_hot_water_offset_f(archived), 2.133)
            self.assertEqual(load_cold_water_offset_f(archived), -1.25)
            self.assertEqual(load_flow_calibration(archived), (0.005, -2.5))

    def test_legacy_power_only_record_exports_coefficients_without_identity(self):
        self.assertEqual(public_calibration_snapshot({
            "manufacturer": "Private", "model_number": "Private model",
            "vrms_scale": 0.01, "irms_offset": 20,
        }), {"vrms_scale": 0.01, "irms_offset": 20})

    def test_malformed_calibration_section_is_rejected(self):
        with self.assertRaises(ValueError):
            public_calibration_snapshot({"power": "invalid"})

    def test_sensor_identity_is_preserved_while_heater_identity_is_removed(self):
        sensor = {"manufacturer": "Sensor Make", "model_number": "Sensor Model",
                  "serial_number": "sensor-123", "year": 2020}
        calibration = {
            "manufacturer": "Heater Make", "model_number": "Heater Model",
            "power": {"manufacturer": "Heater Make", "model_number": "Heater Model",
                      "equipment_id": "wh_test", "sensor": sensor},
            "hot_water_temp": dict(sensor, correction_offset_f=1.5),
            "flow_rate": dict(sensor, scale_gpm_per_count=0.005, offset_gpm=-2),
        }
        sanitized = sanitize_station_calibration(calibration)
        self.assertNotIn("manufacturer", sanitized)
        self.assertNotIn("model_number", sanitized["power"])
        self.assertEqual(sanitized["power"]["equipment_id"], "wh_test")
        self.assertEqual(sanitized["power"]["sensor"], sensor)
        for section in ("hot_water_temp", "flow_rate"):
            self.assertEqual(sanitized[section], calibration[section])
        exported = public_calibration_snapshot(sanitized)
        self.assertEqual(exported, sanitized)
