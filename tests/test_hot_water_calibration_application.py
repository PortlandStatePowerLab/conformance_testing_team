import json
import tempfile
import unittest
from pathlib import Path

from software.sensors import SensorReader
from software.station.station_hardware_map import CH_AMBIENT, CH_COLD, CH_FLOW, CH_HOT


class FakeAdc:
    def read_single(self, channel):
        return self.read_range(CH_HOT, CH_AMBIENT)[channel]

    def read_range(self, _first, _last):
        return {
            CH_HOT: 1428,
            CH_COLD: 1142,
            CH_FLOW: 1033,
            CH_AMBIENT: 228,
        }


class HotWaterCalibrationApplicationTests(unittest.TestCase):
    def test_offset_corrects_hot_c_and_derives_hot_f_without_changing_raw_or_cold(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "WH-station4.json"
            calibration.write_text(
                json.dumps(
                    {"hot_water_temp": {"correction_offset_f": 2.133}}
                ),
                encoding="utf-8",
            )
            nominal = SensorReader(FakeAdc()).get_sensor_snapshot()
            corrected = SensorReader(
                FakeAdc(), station_calibration_path=calibration
            ).get_sensor_snapshot()

        self.assertAlmostEqual(corrected.hot_temp_f, nominal.hot_temp_f + 2.133)
        self.assertAlmostEqual(
            corrected.hot_temp_c,
            nominal.hot_temp_c + (2.133 * 5.0 / 9.0),
        )
        self.assertAlmostEqual(
            corrected.hot_temp_f,
            corrected.hot_temp_c * 9.0 / 5.0 + 32.0,
        )
        self.assertEqual(corrected.hot_raw_counts, nominal.hot_raw_counts)
        self.assertEqual(corrected.cold_temp_c, nominal.cold_temp_c)
        self.assertEqual(corrected.cold_temp_f, nominal.cold_temp_f)

    def test_calibration_can_be_bypassed_for_calibration_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "WH-station4.json"
            calibration.write_text(
                '{"hot_water_temp":{"correction_offset_f":2.133}}',
                encoding="utf-8",
            )
            nominal = SensorReader(FakeAdc()).get_sensor_snapshot()
            bypassed = SensorReader(
                FakeAdc(),
                station_calibration_path=calibration,
                apply_hot_water_calibration=False,
            ).get_sensor_snapshot()

        self.assertEqual(bypassed.hot_temp_c, nominal.hot_temp_c)
        self.assertEqual(bypassed.hot_temp_f, nominal.hot_temp_f)

    def test_existing_station_file_without_hot_section_uses_zero_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "WH-station3.json"
            calibration.write_text('{"vrms_scale":0.01}', encoding="utf-8")
            nominal = SensorReader(FakeAdc()).get_sensor_snapshot()
            legacy = SensorReader(
                FakeAdc(), station_calibration_path=calibration
            ).get_sensor_snapshot()

        self.assertEqual(legacy.hot_temp_c, nominal.hot_temp_c)
        self.assertEqual(legacy.hot_temp_f, nominal.hot_temp_f)

    def test_cold_offset_corrects_both_units_without_changing_raw_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "WH-station1.json"
            calibration.write_text(
                json.dumps(
                    {"cold_water_temp": {"correction_offset_f": -1.642}}
                ),
                encoding="utf-8",
            )
            nominal = SensorReader(FakeAdc()).get_sensor_snapshot()
            corrected = SensorReader(
                FakeAdc(), station_calibration_path=calibration
            ).get_sensor_snapshot()

        self.assertAlmostEqual(corrected.cold_temp_f, nominal.cold_temp_f - 1.642)
        self.assertAlmostEqual(
            corrected.cold_temp_c,
            nominal.cold_temp_c + (-1.642 * 5.0 / 9.0),
        )
        self.assertAlmostEqual(
            corrected.cold_temp_f,
            corrected.cold_temp_c * 9.0 / 5.0 + 32.0,
        )
        self.assertEqual(corrected.cold_raw_counts, nominal.cold_raw_counts)
        self.assertEqual(corrected.hot_temp_f, nominal.hot_temp_f)

    def test_cold_calibration_can_be_bypassed_by_calibration_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "WH-station1.json"
            calibration.write_text(
                '{"cold_water_temp":{"correction_offset_f":-1.642}}',
                encoding="utf-8",
            )
            nominal = SensorReader(FakeAdc()).get_sensor_snapshot()
            bypassed = SensorReader(
                FakeAdc(),
                station_calibration_path=calibration,
                apply_cold_water_calibration=False,
            ).get_sensor_snapshot()

        self.assertEqual(bypassed.cold_temp_c, nominal.cold_temp_c)
        self.assertEqual(bypassed.cold_temp_f, nominal.cold_temp_f)


if __name__ == "__main__":
    unittest.main()
