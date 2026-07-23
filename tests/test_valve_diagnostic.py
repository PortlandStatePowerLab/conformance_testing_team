"""Tests for enabled-output valve diagnostic exception handling."""

from __future__ import annotations

import unittest

from software.valve.valve_diagnostic import run_valve_diagnostic


class FakeValve:
    """Record diagnostic valve commands and inject close failures."""

    def __init__(self, *, close_error: Exception | None = None) -> None:
        """Initialize command counts and an optional close failure."""
        self.open_count = 0
        self.close_count = 0
        self._close_error = close_error

    def open(self) -> None:
        """Record one physical valve-open command."""
        self.open_count += 1

    def close(self) -> None:
        """Record one physical close command and optionally raise."""
        self.close_count += 1
        if self._close_error is not None:
            raise self._close_error


class ValveDiagnosticTest(unittest.TestCase):
    """Verify diagnostic errors remain primary when physical close fails."""

    def test_off_state_closes_without_opening_or_sleeping(self) -> None:
        """Keep the close-only operator command available without a pulse."""
        valve = FakeValve()
        sleep_delays_s: list[float] = []

        run_valve_diagnostic(
            valve=valve,
            requested_state="off",
            pulse_seconds=0.25,
            sleep=sleep_delays_s.append,
        )

        self.assertEqual(valve.open_count, 0)
        self.assertEqual(valve.close_count, 1)
        self.assertEqual(sleep_delays_s, [])

    def test_pulse_error_survives_valve_close_failure(self) -> None:
        """Preserve pulse failure and record a later physical close failure."""
        pulse_error = RuntimeError("pulse failed")
        close_error = RuntimeError("close failed")
        valve = FakeValve(close_error=close_error)

        def fail_sleep(delay_s: float) -> None:
            """Raise the configured pulse failure."""
            raise pulse_error

        with self.assertRaises(RuntimeError) as raised:
            run_valve_diagnostic(
                valve=valve,
                requested_state="on",
                pulse_seconds=0.25,
                sleep=fail_sleep,
            )

        self.assertIs(raised.exception, pulse_error)
        self.assertEqual(
            pulse_error.__notes__,
            [f"Valve close also failed: {close_error!r}"],
        )
        self.assertEqual(valve.open_count, 1)
        self.assertEqual(valve.close_count, 1)


if __name__ == "__main__":
    unittest.main()
