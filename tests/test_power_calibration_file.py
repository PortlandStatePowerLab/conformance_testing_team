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
    "manufacturer": "Example",
    "model_number": "Model A",
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
                        "manufacturer": "American Standard",
                        "model_number": "ASHPWH-50",
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
            self.assertEqual(updated["power"]["manufacturer"], "American Standard")
            self.assertEqual(updated["power"]["model_number"], "ASHPWH-50")
            backups = list(calibration_dir.glob("WH-station4_*.json.save"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                json.loads(backups[0].read_text(encoding="utf-8"))["hot_water_temp"],
                hot,
            )


if __name__ == "__main__":
    unittest.main()
