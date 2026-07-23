"""Laptop-safe tests for the Raspberry Pi GPIO valve driver"""

import unittest
from types import ModuleType

from software.valve.gpio_valve_driver import GpioValveDriver

class FakeGpio(ModuleType):
    """Record GPIO output and cleanup calls without touching real hardware"""

    HIGH = 1
    LOW = 0

    def __init__(self)->None:
        """Initialize an empty fake GPIO call history"""
        super().__init__("fake_gpio")
        self.output_calls: list[tuple[int, int]] = []
        self.cleanup_calls: list[int] = []

    def output(self, pin: int, state: int)->None:
        """Record one requested GPIO output state"""
        self.output_calls.append((pin, state))

    def cleanup(self, pin: int)->None:
        """Record cleanup of one GPIO pin"""
        self.cleanup_calls.append(pin)


class GpioValveDriverTest(unittest.TestCase):
    """Verify valve GPIO commands and resource-lifecycle behavior"""

    def setUp(self)->None:
        """Create a fresh fake GPIO module and valve driver for each test"""
        self.gpio = FakeGpio()
        self.pin = 17
        self.valve = GpioValveDriver(self.gpio, self.pin)

    def test_open_writes_gpio_high(self)->None:
        """Opening the valve should assert the relay output HIGH"""
        self.valve.open()

        self.assertEqual(self.gpio.output_calls, [(self.pin, self.gpio.HIGH)])

    def test_close_writes_gpio_low(self)->None:
        """Closing the valve should return the relay output to LOW"""
        self.valve.close()

        self.assertEqual(self.gpio.output_calls, [(self.pin, self.gpio.LOW)])

    def test_cleanup_forces_low_and_releases_pin_once(self)->None:
        """Cleanup should force LOW and remain safe when called repeatedly"""
        self.valve.cleanup()
        self.valve.cleanup()

        self.assertEqual(self.gpio.output_calls, [(self.pin, self.gpio.LOW)])
        self.assertEqual(self.gpio.cleanup_calls, [self.pin])

    def test_open_afer_cleanup_raises_runtime_error(self)->None:
        """A cleaned-up driver must not issue another GPIO HIGH command"""
        self.valve.cleanup()
        output_call_count = len(self.gpio.output_calls)

        with self.assertRaises(RuntimeError):
            self.valve.open()

        self.assertEqual(len(self.gpio.output_calls), output_call_count)

    def test_close_after_cleanup_raises_runtime_error(self)->None:
        """A cleaned-up driver must not issue another GPIO LOW command"""
        self.valve.cleanup()
        output_call_count = len(self.gpio.output_calls)

        with self.assertRaises(RuntimeError):
            self.valve.close()

        self.assertEqual(len(self.gpio.output_calls), output_call_count)

    def test_cleanup_failure_leaves_driver_retryable(self) -> None:
        """Retry GPIO release without issuing another physical LOW command."""
        cleanup_error = RuntimeError("GPIO cleanup failed")
        original_cleanup = self.gpio.cleanup
        cleanup_attempts = 0

        def fail_first_cleanup(pin: int) -> None:
            """Fail the first release attempt and record a later successful one."""
            nonlocal cleanup_attempts
            cleanup_attempts += 1
            if cleanup_attempts == 1:
                raise cleanup_error
            original_cleanup(pin)

        self.gpio.cleanup = fail_first_cleanup

        with self.assertRaises(RuntimeError) as raised:
            self.valve.cleanup()
        self.valve.cleanup()

        self.assertIs(raised.exception, cleanup_error)
        self.assertEqual(cleanup_attempts, 2)
        self.assertEqual(
            self.gpio.output_calls,
            [(self.pin, self.gpio.LOW)],
        )
        self.assertEqual(self.gpio.cleanup_calls, [self.pin])
        self.assertTrue(self.valve._commands_disabled)
        self.assertTrue(self.valve._cleanup_complete)

    def test_cleanup_failure_disables_open_and_close(self) -> None:
        """Reject later commands without issuing additional GPIO writes."""
        cleanup_error = RuntimeError("GPIO cleanup failed")

        def fail_cleanup(pin: int) -> None:
            """Raise the configured GPIO release failure."""
            raise cleanup_error

        self.gpio.cleanup = fail_cleanup

        with self.assertRaises(RuntimeError):
            self.valve.cleanup()

        output_calls_after_cleanup = list(self.gpio.output_calls)
        with self.assertRaises(RuntimeError):
            self.valve.open()
        with self.assertRaises(RuntimeError):
            self.valve.close()

        self.assertEqual(
            output_calls_after_cleanup,
            [(self.pin, self.gpio.LOW)],
        )
        self.assertEqual(self.gpio.output_calls, output_calls_after_cleanup)
        self.assertTrue(self.valve._commands_disabled)
        self.assertFalse(self.valve._cleanup_complete)

    def test_close_error_survives_gpio_cleanup_failure(self) -> None:
        """Preserve LOW-output failure while recording pin-release failure."""
        close_error = RuntimeError("LOW output failed")
        cleanup_error = RuntimeError("GPIO cleanup failed")
        output_attempts = 0

        def fail_output(pin: int, state: int) -> None:
            """Raise the configured LOW-output failure."""
            nonlocal output_attempts
            output_attempts += 1
            raise close_error

        def fail_cleanup(pin: int) -> None:
            """Raise the configured GPIO pin-release failure."""
            raise cleanup_error

        self.gpio.output = fail_output
        self.gpio.cleanup = fail_cleanup

        with self.assertRaises(RuntimeError) as raised:
            self.valve.cleanup()

        self.assertIs(raised.exception, close_error)
        self.assertEqual(
            close_error.__notes__,
            [f"GPIO pin cleanup also failed: {cleanup_error!r}"],
        )
        self.assertEqual(output_attempts, 1)
        self.assertTrue(self.valve._commands_disabled)
        self.assertFalse(self.valve._cleanup_complete)


if __name__=="__main__":
    unittest.main()
