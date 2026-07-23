"""Laptop-safe tests for GPIO valve construction and initial state."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from software.valve import gpio_valve_builder
from software.valve.gpio_valve_driver import GpioValveDriver


class FakeGpioModule(types.ModuleType):
    """Record GPIO configuration without importing Raspberry Pi hardware."""

    BCM = 11
    OUT = 1
    LOW = 0
    HIGH = 1

    def __init__(self) -> None:
        """Initialize empty GPIO configuration and output histories."""
        super().__init__("RPi.GPIO")
        self.warning_states: list[bool] = []
        self.mode_calls: list[int] = []
        self.setup_calls: list[tuple[int, int, int]] = []
        self.output_calls: list[tuple[int, int]] = []
        self.cleanup_calls: list[int] = []

    def setwarnings(self, enabled: bool) -> None:
        """Record whether GPIO warnings were enabled."""
        self.warning_states.append(enabled)

    def setmode(self, mode: int) -> None:
        """Record the selected GPIO numbering mode."""
        self.mode_calls.append(mode)

    def setup(self, pin: int, mode: int, *, initial: int) -> None:
        """Record output-pin setup and its initial state."""
        self.setup_calls.append((pin, mode, initial))

    def output(self, pin: int, state: int) -> None:
        """Record a valve output request."""
        self.output_calls.append((pin, state))

    def cleanup(self, pin: int) -> None:
        """Record release of one GPIO pin."""
        self.cleanup_calls.append(pin)


def make_fake_rpi_modules(
    gpio_module: FakeGpioModule,
) -> dict[str, types.ModuleType]:
    """Create import-compatible fake ``RPi`` and ``RPi.GPIO`` modules."""
    rpi_module = types.ModuleType("RPi")
    rpi_module.GPIO = gpio_module
    return {"RPi": rpi_module, "RPi.GPIO": gpio_module}


class GpioValveBuilderTest(unittest.TestCase):
    """Verify lazy, safe GPIO setup and driver dependency ownership."""

    def test_builder_configures_requested_pin_low_and_returns_driver(self) -> None:
        """Configure BCM output LOW and retain the same GPIO module and pin."""
        fake_gpio = FakeGpioModule()
        requested_pin = 23

        with patch.dict(sys.modules, make_fake_rpi_modules(fake_gpio)):
            valve = gpio_valve_builder.build_gpio_valve(pin=requested_pin)

        self.assertIsInstance(valve, GpioValveDriver)
        self.assertIs(valve._gpio, fake_gpio)
        self.assertEqual(valve._pin, requested_pin)
        self.assertEqual(fake_gpio.warning_states, [False])
        self.assertEqual(fake_gpio.mode_calls, [fake_gpio.BCM])
        self.assertEqual(
            fake_gpio.setup_calls,
            [(requested_pin, fake_gpio.OUT, fake_gpio.LOW)],
        )


if __name__ == "__main__":
    unittest.main()
