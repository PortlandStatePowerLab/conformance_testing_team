import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from software.calibration_tools.flow_rate_calibration import (
    FlowSample,
    calculate_flow_calibration,
    calibration_section,
    save_flow_calibration,
)


class FlowRateCalibrationTests(unittest.TestCase):
    def test_zero_and_normal_flow_calculate_raw_scale_and_offset(self):
        result = calculate_flow_calibration(
            [477, 478, 477],
            [0.19, 0.20, 0.19],
            [3.0, 3.0, 3.0],
            [
                FlowSample(1032.0, 3.02),
                FlowSample(1033.0, 3.03),
                FlowSample(1031.0, 3.01),
            ],
        )
        expected_scale = 3.0 / (1032.0 - (1432.0 / 3.0))
        self.assertAlmostEqual(result.scale_gpm_per_count, expected_scale)
        self.assertAlmostEqual(
            result.zero_raw_counts * result.scale_gpm_per_count
            + result.offset_gpm,
            0.0,
        )
        self.assertAlmostEqual(
            result.average_flowing_raw_counts * result.scale_gpm_per_count
            + result.offset_gpm,
            3.0,
        )

    def test_section_records_sbn234_and_raw_zero_evidence(self):
        result = calculate_flow_calibration(
            [477, 478],
            [0.19, 0.20],
            [3.0, 3.0, 3.0],
            [FlowSample(1032.0, 3.02)] * 3,
        )
        section = calibration_section(
            result,
            calibrated_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(section["reference_device"], "McMaster-Carr SBN234")
        self.assertEqual(section["zero_raw_count_readings"], [477, 478])

    def test_save_preserves_power_and_temperature_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station2.json"
            original = {
                "power": {"vrms_scale": 0.01},
                "hot_water_temp": {"correction_offset_f": 1.858},
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            backup = save_flow_calibration(
                path,
                {"scale_gpm_per_count": 0.0054},
                saved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
            )
            updated = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(updated["power"], original["power"])
        self.assertEqual(updated["hot_water_temp"], original["hot_water_temp"])
        self.assertEqual(updated["flow_rate"]["scale_gpm_per_count"], 0.0054)
        self.assertIsNotNone(backup)


if __name__ == "__main__":
    unittest.main()
