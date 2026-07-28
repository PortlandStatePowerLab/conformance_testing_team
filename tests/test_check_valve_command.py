"""Laptop-safe tests for valve diagnostic command resource ownership."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from software.commands import check_valve_command
from software.valve.valve_diagnostic import run_valve_diagnostic


class CheckValveCommandTest(unittest.TestCase):
    """Verify default actuation and command-owned driver cleanup."""

    def test_no_arguments_constructs_valve_and_runs_default_open_pulse(self) -> None:
        """Open for 0.25 seconds, physically close, then clean the driver."""
        valve = Mock()
        pulse_delays_s: list[float] = []

        def exercise_diagnostic(
            *,
            valve: object,
            requested_state: str,
            pulse_seconds: float,
        ) -> None:
            """Run the real diagnostic with an injected no-wait pulse timer."""
            run_valve_diagnostic(
                valve=valve,
                requested_state=requested_state,
                pulse_seconds=pulse_seconds,
                sleep=pulse_delays_s.append,
            )

        with (
            patch.object(
                check_valve_command,
                "build_gpio_valve",
                return_value=valve,
            ) as build_valve,
            patch.object(
                check_valve_command,
                "run_valve_diagnostic",
                side_effect=exercise_diagnostic,
            ) as diagnostic,
        ):
            result = check_valve_command.main([])

        self.assertEqual(result, 0)
        build_valve.assert_called_once_with()
        diagnostic.assert_called_once_with(
            valve=valve,
            requested_state="on",
            pulse_seconds=0.25,
        )
        valve.open.assert_called_once_with()
        valve.close.assert_called_once_with()
        self.assertEqual(pulse_delays_s, [0.25])
        valve.cleanup.assert_called_once_with()

    def test_cleans_owned_driver_when_diagnostic_raises(self) -> None:
        """Clean the constructed driver when diagnostic execution fails."""
        valve = Mock()
        diagnostic_error = RuntimeError("diagnostic failed")

        with (
            patch.object(
                check_valve_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(
                check_valve_command,
                "run_valve_diagnostic",
                side_effect=diagnostic_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                check_valve_command.main([])

        self.assertIs(raised.exception, diagnostic_error)
        valve.cleanup.assert_called_once_with()

    def test_diagnostic_error_survives_cleanup_failure(self) -> None:
        """Preserve diagnostic failure and record a later cleanup failure."""
        valve = Mock()
        diagnostic_error = RuntimeError("diagnostic failed")
        cleanup_error = RuntimeError("cleanup failed")
        valve.cleanup.side_effect = cleanup_error

        with (
            patch.object(
                check_valve_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(
                check_valve_command,
                "run_valve_diagnostic",
                side_effect=diagnostic_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                check_valve_command.main([])

        self.assertIs(raised.exception, diagnostic_error)
        self.assertIn(repr(cleanup_error), diagnostic_error.__notes__[0])
        valve.cleanup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
