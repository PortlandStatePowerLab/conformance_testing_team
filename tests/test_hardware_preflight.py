"""Laptop-safe tests for station preflight decision logic."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from software import hardware_preflight


class HardwarePreflightTest(unittest.TestCase):
    def test_schedule_requires_water_draw_only_in_water_mode(self):
        schedule = Path("schedule.csv")
        events = [
            SimpleNamespace(event_type="cta"),
            SimpleNamespace(event_type="water_draw"),
            SimpleNamespace(event_type="water_draw"),
        ]

        with patch.object(hardware_preflight, "load_schedule", return_value=events):
            details = hardware_preflight._schedule_details(schedule, True)

        self.assertEqual(details, "3 enabled events; 2 water draw(s)")

        with patch.object(hardware_preflight, "load_schedule", return_value=[]):
            self.assertEqual(
                hardware_preflight._schedule_details(schedule, False),
                "0 enabled events; 0 water draw(s)",
            )
            with self.assertRaisesRegex(ValueError, "has no water draws"):
                hardware_preflight._schedule_details(schedule, True)

    def test_nominal_sensor_configuration_is_explicit(self):
        self.assertEqual(
            hardware_preflight._sensor_configuration_details(None),
            "nominal sensor configuration",
        )

    def test_i2c_check_accepts_expected_address(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout="     0 1 2 3 4 5 6 7 8 9 a b c d e f\n30: -- -- -- -- -- 35\n",
            stderr="",
        )
        with (
            patch(
                "software.hardware_preflight.shutil.which",
                return_value="/usr/sbin/i2cdetect",
            ),
            patch(
                "software.hardware_preflight.subprocess.run",
                return_value=completed,
            ) as run,
        ):
            details = hardware_preflight._i2c_device_details(1, 0x35)

        self.assertIn("0x35 responded", details)
        self.assertIn("-r", run.call_args.args[0])

    def test_i2c_check_rejects_missing_address(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout="     0 1 2 3 4 5 6 7 8 9 a b c d e f\n30: -- -- -- -- -- --\n",
            stderr="",
        )
        with (
            patch(
                "software.hardware_preflight.shutil.which",
                return_value="/usr/sbin/i2cdetect",
            ),
            patch(
                "software.hardware_preflight.subprocess.run",
                return_value=completed,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "no response"):
                hardware_preflight._i2c_device_details(1, 0x35)

    def test_water_gpio_check_initializes_low_and_cleans_up(self):
        gpio = Mock()
        gpio.BCM = 11
        gpio.OUT = 1
        gpio.LOW = 0
        gpio.input.return_value = gpio.LOW
        with patch(
            "software.hardware_preflight.importlib.import_module",
            return_value=gpio,
        ):
            hardware_preflight._gpio_low_details()

        gpio.setup.assert_called_once_with(
            hardware_preflight.VALVE_PIN,
            gpio.OUT,
            initial=gpio.LOW,
        )
        gpio.cleanup.assert_called_once_with(hardware_preflight.VALVE_PIN)

    def test_main_returns_failure_when_any_check_fails(self):
        checks = [
            hardware_preflight.PreflightCheck("one", True, "ok"),
            hardware_preflight.PreflightCheck("two", False, "missing"),
        ]
        output = io.StringIO()
        with (
            patch(
                "software.hardware_preflight.run_preflight",
                return_value=checks,
            ),
            redirect_stdout(output),
        ):
            result = hardware_preflight.main([])

        self.assertEqual(result, 1)
        self.assertIn("PREFLIGHT_FAIL two: missing", output.getvalue())
        self.assertIn("failed=1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
