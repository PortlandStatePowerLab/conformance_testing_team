import argparse
import unittest

from software.wh_power_monitor import heartbeat_interval, measurement_change_reasons


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


if __name__ == "__main__":
    unittest.main()
