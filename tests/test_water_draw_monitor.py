import csv
import tempfile
import threading
import unittest
from pathlib import Path

from software.helpers.sensor_conversion import (
    NOMINAL_SENSOR_CONFIG,
    counts_to_voltage,
)
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


if __name__ == "__main__":
    unittest.main()
