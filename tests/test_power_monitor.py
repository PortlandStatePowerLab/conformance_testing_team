import argparse
import unittest
from datetime import datetime, timezone

from software.wh_power_monitor import (
    _measurement_row,
    heartbeat_interval,
    measurement_change_reasons,
    pacific_timestamp,
)


def measurement(*, voltage=240.0, current=0.0, power=0.0):
    return {
        "voltage_rms": voltage,
        "current_rms": current,
        "real_power": power,
    }


class PowerMonitorTests(unittest.TestCase):
    def test_heartbeat_cannot_be_less_than_sixty_seconds(self):
        self.assertEqual(heartbeat_interval("60"), 60.0)
        with self.assertRaises(argparse.ArgumentTypeError):
            heartbeat_interval("59.999")

    def test_stable_measurement_has_no_change_reason(self):
        reasons = measurement_change_reasons(
            measurement(),
            measurement(),
            current_change_amps=0.015,
            power_change_watts=25.0,
            voltage_change_volts=1.0,
            on_current_amps=0.1,
        )
        self.assertEqual(reasons, [])

    def test_small_current_change_is_recorded(self):
        reasons = measurement_change_reasons(
            measurement(current=0.016, power=5.0),
            measurement(),
            current_change_amps=0.015,
            power_change_watts=25.0,
            voltage_change_volts=1.0,
            on_current_amps=0.1,
        )
        self.assertIn("current_change", reasons)

    def test_heater_transition_is_recorded(self):
        reasons = measurement_change_reasons(
            measurement(current=0.2, power=40.0),
            measurement(),
            current_change_amps=1.0,
            power_change_watts=100.0,
            voltage_change_volts=10.0,
            on_current_amps=0.1,
        )
        self.assertEqual(reasons, ["heater_on"])

    def test_csv_measurements_are_limited_to_three_decimal_places(self):
        row = _measurement_row(
            {
                "voltage_rms": 238.94819742489267,
                "current_rms": 1.5909564711020525,
                "real_power": 352.84319236727544,
                "reactive_power": 157.57445543547325,
                "apparent_power": 386.8298396180638,
                "power_factor": 0.912109375,
                "voltage_rms_raw": 27574,
            },
            elapsed_seconds=1.23456,
            status="ok",
            reasons=["heartbeat"],
        )
        self.assertEqual(row["monitor_elapsed_seconds"], "1.235")
        self.assertEqual(row["voltage_rms"], "238.948")
        self.assertEqual(row["current_rms"], "1.591")
        self.assertEqual(row["real_power"], "352.843")
        self.assertEqual(row["reactive_power"], "157.574")
        self.assertEqual(row["apparent_power"], "386.830")
        self.assertEqual(row["power_factor"], "0.912")
        self.assertNotIn("voltage_rms_raw", row)

    def test_pacific_timestamp_uses_daylight_and_standard_time_offsets(self):
        summer = pacific_timestamp(
            datetime(2026, 7, 23, 22, 7, 19, 812000, tzinfo=timezone.utc)
        )
        winter = pacific_timestamp(
            datetime(2026, 12, 23, 23, 7, 19, 812000, tzinfo=timezone.utc)
        )
        self.assertEqual(summer, "2026-07-23T15:07:19.812-07:00")
        self.assertEqual(winter, "2026-12-23T15:07:19.812-08:00")
        self.assertNotIn("Z", summer)


if __name__ == "__main__":
    unittest.main()
