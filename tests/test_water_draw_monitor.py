import csv
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from software.helpers.sensor_conversion import (
    NOMINAL_SENSOR_CONFIG,
    counts_to_voltage,
)
from software.sensors.sensor_reader import SensorSnapshot
from software.water_draw_monitor import (
    EXIT_SUCCESS,
    build_parser,
    integrate_volume_gallons,
    run_draw,
)


class WaterDrawTests(unittest.TestCase):
    def test_nominal_flow_integration(self):
        self.assertAlmostEqual(integrate_volume_gallons(3.0, 0.5), 0.025)

    def test_adc_conversion_uses_4096_code_divisor(self):
        self.assertAlmostEqual(
            counts_to_voltage(2048, NOMINAL_SENSOR_CONFIG), 2.048
        )

    def test_default_sample_interval_is_half_second(self):
        args = build_parser().parse_args(
            ["--event-id", "draw_1", "--target-gal", "1"]
        )
        self.assertEqual(args.sample_interval_seconds, 0.5)

    def test_dry_run_writes_csv_without_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "draw.csv"
            args = build_parser().parse_args(
                [
                    "--event-id",
                    "draw_1",
                    "--target-gal",
                    "1",
                    "--output-csv",
                    str(output),
                ]
            )
            result = run_draw(args, threading.Event())
            self.assertEqual(result, EXIT_SUCCESS)
            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["status"], "dry_run")
            self.assertEqual(rows[0]["valve_state"], "not_configured")

    def test_enabled_draw_uses_valve_package_and_cleans_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "draw.csv"
            args = build_parser().parse_args(
                [
                    "--event-id",
                    "draw_1",
                    "--target-gal",
                    "1",
                    "--output-csv",
                    str(output),
                    "--enable-output",
                ]
            )
            stop_event = threading.Event()
            valve = Mock()
            adc = Mock()
            snapshot = SensorSnapshot(
                hot_raw_counts=100,
                cold_raw_counts=200,
                flow_raw_counts=300,
                ambient_raw_counts=400,
                hot_temp_c=50.0,
                hot_temp_f=122.0,
                cold_temp_c=20.0,
                cold_temp_f=68.0,
                ambient_temp_c=22.0,
                ambient_temp_f=71.6,
                flow_gpm=1.0,
            )

            with (
                patch(
                    "software.water_draw_monitor.build_gpio_valve",
                    return_value=valve,
                ) as build_valve,
                patch(
                    "software.water_draw_monitor.build_max1238",
                    return_value=adc,
                ) as build_adc,
                patch("software.water_draw_monitor.SensorReader") as sensor_reader,
                patch(
                    "software.water_draw_monitor.time.monotonic",
                    side_effect=[0.0, 60.0, 60.0],
                ),
            ):
                sensor_reader.return_value.get_sensor_snapshot.return_value = snapshot
                result = run_draw(args, stop_event)

            self.assertEqual(result, EXIT_SUCCESS)
            build_valve.assert_called_once_with()
            build_adc.assert_called_once_with()
            sensor_reader.assert_called_once_with(adc, configuration_path=None)
            sensor_reader.return_value.get_sensor_snapshot.assert_called_once_with()
            valve.open.assert_called_once_with()
            valve.cleanup.assert_called_once_with()
            adc.close.assert_called_once_with()
            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["flow_gpm"], "1.0")
            self.assertEqual(rows[-1]["stop_reason"], "target_reached")


if __name__ == "__main__":
    unittest.main()
