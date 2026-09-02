import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from software.calibration_tool.hot_water_temp_calibration import (
    CalibrationTimedOut,
    calculate_hot_water_calibration,
    calibration_section,
    save_hot_water_calibration,
    run,
)


class FakeReader:
    def __init__(self, temperatures, raw_counts):
        self.snapshots = iter(
            SimpleNamespace(hot_temp_f=temp, hot_raw_counts=raw)
            for temp, raw in zip(temperatures, raw_counts)
        )

    def get_sensor_snapshot(self):
        return next(self.snapshots)


class HotWaterTemperatureCalibrationTests(unittest.TestCase):
    def test_three_checks_calculate_average_offset_and_keep_raw_values(self):
        reader = FakeReader([119.5, 119.8, 120.1], [1427, 1428, 1430])
        references = iter([125.0, 125.1, 125.2])
        result = calculate_hot_water_calibration(
            reader,
            lambda _check, _deadline: next(references),
            deadline=120.0,
            monotonic=lambda: 0.0,
        )
        self.assertAlmostEqual(result.average_reference_temp_f, 125.1)
        self.assertAlmostEqual(result.average_uncalibrated_temp_f, 119.8)
        self.assertAlmostEqual(result.correction_offset_f, 5.3)
        self.assertAlmostEqual(result.average_raw_counts, 1428.3333333333)
        self.assertEqual(result.raw_count_readings, (1427, 1428, 1430))

    def test_deadline_stops_before_another_check(self):
        with self.assertRaises(CalibrationTimedOut):
            calculate_hot_water_calibration(
                FakeReader([120.0], [1428]),
                lambda _check, _deadline: 125.0,
                deadline=120.0,
                monotonic=lambda: 120.0,
            )

    def test_save_preserves_flat_power_fields_and_creates_complete_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WH-station3.json"
            old_document = {
                "vrms_scale": 0.01,
                "irms_scale": 0.002,
                "vrms_offset": 10,
                "irms_offset": 20,
                "future_unknown_field": {"keep": True},
            }
            path.write_text(json.dumps(old_document), encoding="utf-8")
            section = {"correction_offset_f": 5.3}
            timestamp = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)

            backup = save_hot_water_calibration(path, section, saved_at=timestamp)

            self.assertIsNotNone(backup)
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), old_document)
            updated = json.loads(path.read_text(encoding="utf-8"))
            for key, value in old_document.items():
                self.assertEqual(updated[key], value)
            self.assertEqual(updated["hot_water_temp"], section)

    def test_section_records_simple_thermometer_information(self):
        result = calculate_hot_water_calibration(
            FakeReader([120.0, 120.0, 120.0], [1428, 1428, 1428]),
            lambda _check, _deadline: 125.0,
            deadline=120.0,
            monotonic=lambda: 0.0,
        )
        section = calibration_section(
            result,
            calibrated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(section["thermometer_used"], "Bomata T101A")
        self.assertEqual(section["thermometer_accuracy_f"], 1.8)
        self.assertEqual(section["correction_offset_f"], 5.0)

    def test_run_closes_valve_after_third_check_and_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                station="WH-station3",
                calibration_dir=Path(directory),
            )
            valve = Mock()
            sensor_reader = Mock()
            sensor_reader.get_sensor_snapshot.side_effect = [
                SimpleNamespace(hot_temp_f=70.0, hot_raw_counts=1000),
                SimpleNamespace(hot_temp_f=120.0, hot_raw_counts=1428),
                SimpleNamespace(hot_temp_f=120.0, hot_raw_counts=1428),
                SimpleNamespace(hot_temp_f=120.0, hot_raw_counts=1428),
            ]
            session = SimpleNamespace(reader=sensor_reader, close=Mock())
            references = iter([125.0, 125.0, 125.0])
            with (
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.build_gpio_valve",
                    return_value=valve,
                ),
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.build_station_sensor_session",
                    return_value=session,
                ),
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.console_reference_reader",
                    side_effect=lambda _check, _deadline: next(references),
                ),
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.time.monotonic",
                    return_value=0.0,
                ),
            ):
                self.assertEqual(run(args), 0)

            valve.open.assert_called_once_with()
            valve.close.assert_called_once_with()
            valve.cleanup.assert_called_once_with()
            session.close.assert_called_once_with()
            saved = json.loads(
                (Path(directory) / "WH-station3.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["hot_water_temp"]["correction_offset_f"], 5.0)

    def test_run_timeout_cleans_up_without_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                station="WH-station3",
                calibration_dir=Path(directory),
            )
            valve = Mock()
            sensor_reader = Mock()
            sensor_reader.get_sensor_snapshot.return_value = SimpleNamespace(
                hot_temp_f=120.0, hot_raw_counts=1428
            )
            session = SimpleNamespace(reader=sensor_reader, close=Mock())
            with (
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.build_gpio_valve",
                    return_value=valve,
                ),
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.build_station_sensor_session",
                    return_value=session,
                ),
                patch(
                    "software.calibration_tool.hot_water_temp_calibration.time.monotonic",
                    side_effect=[0.0, 240.0],
                ),
            ):
                with self.assertRaises(CalibrationTimedOut):
                    run(args)

            valve.open.assert_called_once_with()
            valve.cleanup.assert_called_once_with()
            session.close.assert_called_once_with()
            self.assertFalse((Path(directory) / "WH-station3.json").exists())


if __name__ == "__main__":
    unittest.main()
