"""Laptop-safe tests for controlled water-draw command ownership."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from software.commands import run_water_draw_command


class RunWaterDrawCommandTest(unittest.TestCase):
    def _resources(self):
        events: list[str] = []
        session = Mock()
        session.reader = Mock()
        valve = Mock()
        valve.cleanup.side_effect = lambda: events.append("valve.cleanup")
        session.close.side_effect = lambda: events.append("session.close")
        return events, session, valve

    def test_valid_target_prefetches_and_cleans_in_order(self) -> None:
        events, session, valve = self._resources()
        with (
            patch.object(
                run_water_draw_command,
                "build_station_sensor_session",
                return_value=session,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(
                run_water_draw_command,
                "run_controlled_water_draw",
            ) as workflow,
        ):
            result = run_water_draw_command.main(
                ["--target-gal", "2.5", "--max-run-minutes", "3"]
            )

        self.assertEqual(result, 0)
        session.reader.get_sensor_snapshot.assert_called_once_with()
        workflow.assert_called_once_with(
            2.5,
            sensor_reader=session.reader,
            valve=valve,
            max_run_minutes=3.0,
        )
        self.assertEqual(events, ["valve.cleanup", "session.close"])

    def test_workflow_failure_attempts_both_cleanups(self) -> None:
        events, session, valve = self._resources()
        workflow_error = RuntimeError("workflow failed")
        with (
            patch.object(
                run_water_draw_command,
                "build_station_sensor_session",
                return_value=session,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(
                run_water_draw_command,
                "run_controlled_water_draw",
                side_effect=workflow_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, workflow_error)
        self.assertEqual(events, ["valve.cleanup", "session.close"])

    def test_valve_build_failure_closes_sensor_session(self) -> None:
        events, session, _ = self._resources()
        build_error = RuntimeError("valve build failed")
        with (
            patch.object(
                run_water_draw_command,
                "build_station_sensor_session",
                return_value=session,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                side_effect=build_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, build_error)
        self.assertEqual(events, ["session.close"])

    def test_workflow_error_survives_both_cleanup_failures(self) -> None:
        _, session, valve = self._resources()
        workflow_error = RuntimeError("workflow failed")
        valve_error = RuntimeError("valve cleanup failed")
        session_error = RuntimeError("session cleanup failed")
        valve.cleanup.side_effect = valve_error
        session.close.side_effect = session_error
        with (
            patch.object(
                run_water_draw_command,
                "build_station_sensor_session",
                return_value=session,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(
                run_water_draw_command,
                "run_controlled_water_draw",
                side_effect=workflow_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, workflow_error)
        self.assertEqual(
            workflow_error.__notes__,
            [
                f"Valve cleanup also failed: {valve_error!r}",
                f"Sensor session cleanup also failed: {session_error!r}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
