"""Tests for pure sensor-conversion helpers."""

from __future__ import annotations

import unittest

from software.sensors.sensor_conversion_math import (
    NOMINAL_SENSOR_CONFIG,
    lm35_voltage_to_temp_f,
    temp_c_to_temp_f,
)


class SensorConversionTest(unittest.TestCase):
    """Verify standalone sensor-conversion math."""

    def test_temp_c_to_temp_f_converts_known_temperatures(self) -> None:
        self.assertEqual(temp_c_to_temp_f(0.0), 32.0)
        self.assertEqual(temp_c_to_temp_f(100.0), 212.0)
        self.assertEqual(temp_c_to_temp_f(-40.0), -40.0)

    def test_lm35_voltage_to_temp_f_converts_from_sensor_voltage(self) -> None:
        self.assertEqual(lm35_voltage_to_temp_f(0.0), 32.0)
        self.assertEqual(lm35_voltage_to_temp_f(1.0), 212.0)

    def test_temperature_span_f_uses_configured_temperature_limits(self) -> None:
        temperature_span_f = NOMINAL_SENSOR_CONFIG.temperature_span_f

        self.assertEqual(temperature_span_f.engineering_min_value, -58.0)
        self.assertEqual(temperature_span_f.engineering_max_value, 302.0)
        self.assertEqual(temperature_span_f.units, "degF")

    def test_temperature_span_matches_installed_hsm100_range(self) -> None:
        temperature_span = NOMINAL_SENSOR_CONFIG.temperature_span
        degrees_c_per_ma = (
            temperature_span.engineering_max_value
            - temperature_span.engineering_min_value
        ) / 16.0

        self.assertEqual(temperature_span.engineering_min_value, -50.0)
        self.assertEqual(temperature_span.engineering_max_value, 150.0)
        self.assertEqual(degrees_c_per_ma, 12.5)
        self.assertEqual(temperature_span.units, "degC")

    def test_flow_span_matches_installed_sbn234_range(self) -> None:
        flow_span = NOMINAL_SENSOR_CONFIG.flow_span

        self.assertEqual(flow_span.engineering_min_value, 0.2)
        self.assertEqual(flow_span.engineering_max_value, 10.0)
        self.assertEqual(flow_span.units, "gpm")


if __name__ == "__main__":
    unittest.main()
