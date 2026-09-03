import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from software.calibration_tools import power_calibration


class PowerCalibrationToolTests(unittest.TestCase):
    def test_default_paths_resolve_to_repository_saved_data(self):
        repository = Path(power_calibration.__file__).resolve().parents[2]
        self.assertEqual(power_calibration.REPOSITORY_ROOT, repository)
        self.assertEqual(
            power_calibration.DEFAULT_CALIBRATION_DIRECTORY,
            repository / "saved_data" / "calibration",
        )

    def test_parser_does_not_require_pi_hardware(self):
        args = power_calibration.build_parser().parse_args([])
        self.assertEqual(
            args.calibration_dir,
            power_calibration.DEFAULT_CALIBRATION_DIRECTORY,
        )

    def test_monitor_prints_calibrated_values_without_creating_a_csv(self):
        measurement = {
            "voltage_rms": 240.1,
            "current_rms": 20.05,
            "real_power": 4800.0,
            "reactive_power": 12.0,
            "apparent_power": 4814.0,
            "power_factor": 0.997,
            "voltage_rms_raw": 1234,
            "current_rms_raw": 5678,
        }
        times = iter([0.0, 0.0, 1.0])
        output = io.StringIO()
        with redirect_stdout(output):
            power_calibration.monitor_power(
                Mock(),
                {},
                1.0,
                read_measurement=lambda _bus, _calibration: measurement,
                monotonic=lambda: next(times),
                sleep=lambda _seconds: None,
            )

        text = output.getvalue()
        self.assertIn("Vrms=240.1", text)
        self.assertIn("Irms=20.05", text)
        self.assertIn("P=4800.0 W", text)
        self.assertIn("raw vr=1234 ir=5678", text)

    def test_invalid_duration_defaults_to_five_minutes(self):
        with (
            patch("builtins.input", side_effect=["bad"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                power_calibration.prompt_monitor_duration_seconds(),
                300,
            )


if __name__ == "__main__":
    unittest.main()
