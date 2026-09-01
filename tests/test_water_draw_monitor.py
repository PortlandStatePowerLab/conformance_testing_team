import csv
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from software.helpers.sensor_conversion import (
    NOMINAL_SENSOR_CONFIG,
    counts_to_voltage,
)
from software.sensors import SensorSnapshot
from software.water_draw_monitor import (
    EXIT_SUCCESS,
    build_parser,
    integrate_volume_gallons,
    run_draw,
    temperature_arm_threshold_f,
)


class WaterDrawTests(unittest.TestCase):
    def test_temp_drop_arms_then_requires_twenty_consecutive_low_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "draw.csv"
            args = build_parser().parse_args([
                "--event-id", "draw_1", "--draw-type", "temp_drop",
                "--temp-set-f", "125", "--temp-drop-f", "15",
                "--max-run-minutes", "60", "--output-csv", str(output),
                "--enable-output",
            ])
            valve = Mock()
            base = dict(
                hot_raw_counts=100, cold_raw_counts=200, flow_raw_counts=300,
                ambient_raw_counts=400, hot_temp_c=50.0, cold_temp_c=20.0,
                cold_temp_f=68.0, ambient_temp_c=22.0, ambient_temp_f=71.6,
                flow_gpm=1.0,
            )
            temperatures = (
                [75.0, 115.0]
                + [109.0] * 19
                + [111.0]
                + [110.00000000000006] * 20
            )
            snapshots = [SensorSnapshot(hot_temp_f=value, **base) for value in temperatures]
            sensor_reader = Mock()
            sensor_reader.get_sensor_snapshot.side_effect = [snapshots[0], *snapshots]
            session = SimpleNamespace(reader=sensor_reader, close=Mock())
            times = [0.0] + [index * 0.5 for index in range(1, len(snapshots) + 1)] + [30.0]
            with (
                patch("software.water_draw_monitor.build_gpio_valve", return_value=valve),
                patch("software.water_draw_monitor.build_station_sensor_session", return_value=session),
                patch("software.water_draw_monitor.time.monotonic", side_effect=times),
            ):
                stop_event = Mock()
                stop_event.is_set.return_value = False
                result = run_draw(args, stop_event)
            self.assertEqual(result, EXIT_SUCCESS)
            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[-1]["stop_reason"], "temperature_threshold_reached")
            self.assertEqual(len([row for row in rows if row["status"] == "drawing"]), len(snapshots))

    def test_nominal_flow_integration(self):
        self.assertAlmostEqual(integrate_volume_gallons(3.0, 0.5), 0.025)

    def test_arm_temperature_uses_two_thirds_of_selected_drop(self):
        self.assertAlmostEqual(temperature_arm_threshold_f(125.0, 5.0), 121.6666666667)
        self.assertAlmostEqual(temperature_arm_threshold_f(125.0, 10.0), 118.3333333333)
        self.assertAlmostEqual(temperature_arm_threshold_f(125.0, 15.0), 115.0)

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
            sensor_reader = Mock()
            sensor_session = SimpleNamespace(
                reader=sensor_reader,
                close=Mock(),
            )
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
                    "software.water_draw_monitor.build_station_sensor_session",
                    return_value=sensor_session,
                ) as build_sensors,
                patch(
                    "software.water_draw_monitor.time.monotonic",
                    side_effect=[0.0, 60.0, 60.0],
                ),
            ):
                sensor_reader.get_sensor_snapshot.return_value = snapshot
                result = run_draw(args, stop_event)

            self.assertEqual(result, EXIT_SUCCESS)
            build_valve.assert_called_once_with()
            build_sensors.assert_called_once()
            self.assertEqual(sensor_reader.get_sensor_snapshot.call_count, 2)
            valve.open.assert_called_once_with()
            valve.cleanup.assert_called_once_with()
            sensor_session.close.assert_called_once_with()
            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["flow_gpm"], "1.000000")
            self.assertEqual(rows[0]["hot_temp_c"], "50.00")
            self.assertEqual(rows[0]["hot_temp_f"], "122.00")
            self.assertEqual(rows[0]["cold_temp_c"], "20.00")
            self.assertEqual(rows[0]["cold_temp_f"], "68.00")
            self.assertEqual(rows[0]["ambient_temp_c"], "22.00")
            self.assertEqual(rows[0]["ambient_temp_f"], "71.60")
            self.assertEqual(rows[-1]["stop_reason"], "target_reached")


if __name__ == "__main__":
    unittest.main()
