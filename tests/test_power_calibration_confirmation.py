import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from software.helpers.helper_power_functions import calibrate


class PowerCalibrationConfirmationTests(unittest.TestCase):
    def exercise(self, previous_id, answers, reads):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        directory = root / "calibration"
        private = root / "private" / "equipment"
        directory.mkdir()
        private.mkdir(parents=True)
        (private / "WH-station1.json").write_text(json.dumps({"equipment_id": "wh_current"}))
        power = {"equipment_id": previous_id, "vrms_scale": .01, "irms_scale": .002,
                 "vrms_offset": 0, "irms_offset": 0,
                 "sensor": {"manufacturer": "Sensor Make", "model_number": "Sensor Model"}}
        original = {"equipment_id": previous_id, "power": power,
                    "hot_water_temp": {"correction_offset_f": 1.5},
                    "flow_rate": {"scale_gpm_per_count": .005, "sensor_id": "flow_1"}}
        path = directory / "WH-station1.json"
        original_text = json.dumps(original)
        path.write_text(original_text)
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers) as prompt, patch(
            "software.helpers.helper_power_functions.read_raw_measurement_values",
            side_effect=reads,
        ) as read, redirect_stdout(output):
            saved = calibrate(object(), power, str(directory), str(root), hostname="WH-station1")
        self.assertEqual(power, original["power"])
        return saved, path, original, original_text, output.getvalue(), prompt, read

    def test_mismatch_defaults_to_cancel_before_measurement(self):
        for answer in ("", "n", "anything"):
            with self.subTest(answer=answer):
                saved, path, _, text, output, prompt, read = self.exercise("wh_old", [answer], [])
                self.assertFalse(saved)
                self.assertEqual(path.read_text(), text)
                self.assertEqual(list(path.parent.glob("*.save")), [])
                read.assert_not_called()
                self.assertIn("wh_old", output)
                self.assertIn("wh_current", output)
                self.assertIn("[y/N]", prompt.call_args.args[0])

    def test_accept_mismatch_saves_new_id_and_keeps_previous_backup(self):
        saved, path, original, _, _, _, read = self.exercise(
            "wh_old", ["yes", "", "", "240", "", "20", "", "y"], self.readings())
        self.assertTrue(saved)
        self.assertEqual(read.call_count, 4)
        actual = json.loads(path.read_text())
        self.assertEqual(actual["equipment_id"], "wh_current")
        self.assertEqual(actual["power"]["equipment_id"], "wh_current")
        self.assertEqual(actual["power"]["vrms_scale"], 240 / 1000)
        self.assertEqual(actual["power"]["sensor"], original["power"]["sensor"])
        for section in ("hot_water_temp", "flow_rate"):
            self.assertEqual(actual[section], original[section])
        backup = next(path.parent.glob("*.save"))
        self.assertEqual(json.loads(backup.read_text()), original)

    def test_matching_id_needs_only_normal_save_confirmation(self):
        saved, _, _, _, output, prompt, _ = self.exercise(
            "wh_current", ["", "", "240", "", "20", "", "y"], self.readings())
        self.assertTrue(saved)
        self.assertNotIn("WARNING", output)
        self.assertEqual(prompt.call_count, 7)

    def test_accepted_mismatch_then_declined_save_leaves_original(self):
        saved, path, _, text, _, _, _ = self.exercise(
            "wh_old", ["y", "", "", "240", "", "20", "", "n"], self.readings())
        self.assertFalse(saved)
        self.assertEqual(path.read_text(), text)
        self.assertEqual(list(path.parent.glob("*.save")), [])

    def test_accepted_mismatch_then_failed_measurement_leaves_original(self):
        saved, path, _, text, _, _, _ = self.exercise("wh_old", ["y", ""], [None])
        self.assertFalse(saved)
        self.assertEqual(path.read_text(), text)
        self.assertEqual(list(path.parent.glob("*.save")), [])

    @staticmethod
    def readings():
        return [{"voltage_rms_raw": 10}, {"current_rms_raw": 20},
                {"voltage_rms_raw": 1010}, {"current_rms_raw": 1020}]
