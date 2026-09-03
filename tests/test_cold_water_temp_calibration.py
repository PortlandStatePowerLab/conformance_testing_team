import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from software.calibration_tools.cold_water_temp_calibration import (
    CalibrationTimedOut,
    calculate_cold_water_calibration,
    calibration_section,
    run,
    save_cold_water_calibration,
)


class FakeReader:
    def __init__(self, temperatures, raw_counts):
        self.snapshots = iter(
            SimpleNamespace(cold_temp_f=temp, cold_raw_counts=raw)
            for temp, raw in zip(temperatures, raw_counts)
        )

    def get_sensor_snapshot(self):
        return next(self.snapshots)


class ColdWaterTempCalibrationTests(unittest.TestCase):
    def test_three_checks_calculate_cold_average_offset(self):
        reader = FakeReader([65.0, 65.2, 65.1], [1135, 1136, 1135])
        references = iter([66.0, 66.1, 66.2])
        result = calculate_cold_water_calibration(
            reader,
            lambda _check, _deadline: next(references),
            deadline=240.0,
            monotonic=lambda: 0.0,
        )
        self.assertAlmostEqual(result.average_reference_temp_f, 66.1)
        self.assertAlmostEqual(result.average_uncalibrated_temp_f, 65.1)
        self.assertAlmostEqual(result.correction_offset_f, 1.0)
        self.assertEqual(result.raw_count_readings, (1135, 1136, 1135))

    def test_save_preserves_power_and_hot_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station1.json"
            original = {
                "power": {"vrms_scale": 0.01},
                "hot_water_temp": {"correction_offset_f": -1.15},
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            backup = save_cold_water_calibration(
                path,
                {"correction_offset_f": 1.0},
                saved_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            )
            updated = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(updated["power"], original["power"])
        self.assertEqual(updated["hot_water_temp"], original["hot_water_temp"])
        self.assertEqual(updated["cold_water_temp"]["correction_offset_f"], 1.0)
        self.assertIsNotNone(backup)

    def test_non_parent_station_is_rejected_before_hardware(self):
        args = SimpleNamespace(
            station="WH-station2",
            calibration_dir=Path("calibration"),
        )
        with patch(
            "software.calibration_tools.cold_water_temp_calibration.build_gpio_valve"
        ) as build_valve:
            with self.assertRaisesRegex(ValueError, "only on WH-station1"):
                run(args)
        build_valve.assert_not_called()

    def test_section_records_bomata_information(self):
        result = calculate_cold_water_calibration(
            FakeReader([65.0] * 3, [1135] * 3),
            lambda _check, _deadline: 66.0,
            deadline=240.0,
            monotonic=lambda: 0.0,
        )
        section = calibration_section(
            result,
            calibrated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(section["thermometer_used"], "Bomata T101A")
        self.assertEqual(section["thermometer_accuracy_f"], 1.8)


if __name__ == "__main__":
    unittest.main()
