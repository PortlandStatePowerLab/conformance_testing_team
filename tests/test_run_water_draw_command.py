"""Laptop-safe tests for controlled water-draw command ownership."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from software.commands import run_water_draw_command


class RunWaterDrawCommandTest(unittest.TestCase):
    """Verify dependency construction and command-owned cleanup."""

    def test_valid_target_constructs_resources_and_cleans_in_order(self) -> None:
        """Construct real dependencies, then release valve before ADC."""
        events: list[str] = []
        adc = Mock()
        valve = Mock()
        adc.close.side_effect = lambda: events.append("adc.close")
        valve.cleanup.side_effect = lambda: events.append("valve.cleanup")

        with (
            patch.object(
                run_water_draw_command,
                "build_max1238",
                return_value=adc,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(
                run_water_draw_command,
                "SensorReader",
                side_effect=lambda built_adc: ("reader", built_adc),
            ),
            patch.object(
                run_water_draw_command,
                "run_controlled_water_draw",
            ) as workflow,
        ):
            result = run_water_draw_command.main(
                [
                    "--target-gal",
                    "2.5",
                    "--max-run-minutes",
                    "3",
                ]
            )

        self.assertEqual(result, 0)
        workflow.assert_called_once_with(
            2.5,
            sensor_reader=("reader", adc),
            valve=valve,
            max_run_minutes=3.0,
        )
        valve.open.assert_not_called()
        valve.close.assert_not_called()
        self.assertEqual(events, ["valve.cleanup", "adc.close"])

    def test_workflow_failure_attempts_both_resource_cleanups(self) -> None:
        """Clean the valve and ADC when the controlled workflow raises."""
        events: list[str] = []
        adc = Mock()
        valve = Mock()
        workflow_error = RuntimeError("workflow failed")
        valve.cleanup.side_effect = lambda: events.append("valve.cleanup")
        adc.close.side_effect = lambda: events.append("adc.close")

        with (
            patch.object(
                run_water_draw_command,
                "build_max1238",
                return_value=adc,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(run_water_draw_command, "SensorReader"),
            patch.object(
                run_water_draw_command,
                "run_controlled_water_draw",
                side_effect=workflow_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, workflow_error)
        self.assertEqual(events, ["valve.cleanup", "adc.close"])

    def test_adc_close_is_attempted_when_valve_cleanup_raises(self) -> None:
        """Preserve valve cleanup failure while still attempting ADC closure."""
        adc = Mock()
        valve = Mock()
        cleanup_error = RuntimeError("valve cleanup failed")
        valve.cleanup.side_effect = cleanup_error

        with (
            patch.object(
                run_water_draw_command,
                "build_max1238",
                return_value=adc,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(run_water_draw_command, "SensorReader"),
            patch.object(run_water_draw_command, "run_controlled_water_draw"),
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, cleanup_error)
        adc.close.assert_called_once_with()

    def test_valve_build_failure_closes_constructed_adc(self) -> None:
        """Close the ADC if valve construction fails after ADC construction."""
        adc = Mock()
        build_error = RuntimeError("valve build failed")

        with (
            patch.object(
                run_water_draw_command,
                "build_max1238",
                return_value=adc,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                side_effect=build_error,
            ),
            patch.object(run_water_draw_command, "run_controlled_water_draw") as workflow,
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, build_error)
        workflow.assert_not_called()
        adc.close.assert_called_once_with()

    def test_workflow_error_survives_both_cleanup_failures(self) -> None:
        """Preserve workflow failure and record both later release failures."""
        adc = Mock()
        valve = Mock()
        workflow_error = RuntimeError("workflow failed")
        valve_cleanup_error = RuntimeError("valve cleanup failed")
        adc_close_error = RuntimeError("ADC close failed")
        valve.cleanup.side_effect = valve_cleanup_error
        adc.close.side_effect = adc_close_error

        with (
            patch.object(
                run_water_draw_command,
                "build_max1238",
                return_value=adc,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(run_water_draw_command, "SensorReader"),
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
                f"Valve cleanup also failed: {valve_cleanup_error!r}",
                f"ADC close also failed: {adc_close_error!r}",
            ],
        )
        valve.cleanup.assert_called_once_with()
        adc.close.assert_called_once_with()

    def test_valve_cleanup_error_survives_adc_close_failure(self) -> None:
        """Preserve the first release failure while recording ADC close failure."""
        adc = Mock()
        valve = Mock()
        valve_cleanup_error = RuntimeError("valve cleanup failed")
        adc_close_error = RuntimeError("ADC close failed")
        valve.cleanup.side_effect = valve_cleanup_error
        adc.close.side_effect = adc_close_error

        with (
            patch.object(
                run_water_draw_command,
                "build_max1238",
                return_value=adc,
            ),
            patch.object(
                run_water_draw_command,
                "build_gpio_valve",
                return_value=valve,
            ),
            patch.object(run_water_draw_command, "SensorReader"),
            patch.object(run_water_draw_command, "run_controlled_water_draw"),
        ):
            with self.assertRaises(RuntimeError) as raised:
                run_water_draw_command.main(["--target-gal", "1"])

        self.assertIs(raised.exception, valve_cleanup_error)
        self.assertEqual(
            valve_cleanup_error.__notes__,
            [f"ADC close also failed: {adc_close_error!r}"],
        )


if __name__ == "__main__":
    unittest.main()
