"""Tests for the hardware-independent sensor-check assembly point."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from software.station.station_hardware_map import (
    CH_AMBIENT,
    CH_COLD,
    CH_FLOW,
    CH_HOT,
)
from software.commands import check_sensors_command as sensor_check


class FakeAdc:
    """Provide deterministic grouped counts without importing Pi hardware."""

    def __init__(self) -> None:
        self.read_range_calls = 0
        self.closed = False

    def read_single(self, channel: int, /) -> int:
        raise AssertionError("A sensor snapshot must use one grouped read")

    def read_range(
        self,
        first_channel: int,
        last_channel: int,
        /,
    ) -> dict[int, int]:
        self.read_range_calls += 1
        self.requested_range = (first_channel, last_channel)
        return {
            CH_HOT: 1000,
            CH_COLD: 900,
            CH_FLOW: 800,
            CH_AMBIENT: 700,
        }

    def close(self) -> None:
        self.closed = True


class FakeReader:
    """Provide deterministic snapshots for watch-mode reporting tests."""

    def __init__(self, snapshots: list[sensor_check.SensorSnapshot]) -> None:
        self._snapshots = snapshots
        self.get_sensor_snapshot_calls = 0

    def get_sensor_snapshot(self) -> sensor_check.SensorSnapshot:
        if self.get_sensor_snapshot_calls >= len(self._snapshots):
            raise KeyboardInterrupt

        snapshot = self._snapshots[self.get_sensor_snapshot_calls]
        self.get_sensor_snapshot_calls += 1
        return snapshot


class SensorCheckTest(unittest.TestCase):
    """Verify one-shot diagnostic assembly with a pure fake ADC."""

    def make_snapshot(self, *, flow_raw_counts: int) -> sensor_check.SensorSnapshot:
        return sensor_check.SensorSnapshot(
            hot_raw_counts=1000,
            cold_raw_counts=900,
            flow_raw_counts=flow_raw_counts,
            ambient_raw_counts=700,
            hot_temp_c=25.0,
            hot_temp_f=77.0,
            cold_temp_c=20.0,
            cold_temp_f=68.0,
            ambient_temp_c=22.0,
            ambient_temp_f=71.6,
            flow_gpm=1.5,
        )

    def test_main_builds_once_prints_one_grouped_snapshot_and_closes(self) -> None:
        fake_adc = FakeAdc()
        captured_output = io.StringIO()

        with (
            patch.object(
                sensor_check,
                "build_max1238",
                return_value=fake_adc,
            ) as build_max1238,
            contextlib.redirect_stdout(captured_output),
        ):
            exit_code = sensor_check.main([])

        self.assertEqual(exit_code, 0)
        build_max1238.assert_called_once_with()
        self.assertEqual(fake_adc.read_range_calls, 1)
        self.assertEqual(fake_adc.requested_range, (CH_HOT, CH_AMBIENT))
        self.assertTrue(fake_adc.closed)
        self.assertNotIn("software.adc.max1238_driver", sys.modules)
        self.assertNotIn("smbus2", sys.modules)

        output = captured_output.getvalue()
        for report_text in (
            "Sensor snapshot at ",
            "Raw ADC counts",
            "  hot_raw_counts    : 1000 counts",
            "  cold_raw_counts   : 900 counts",
            "  flow_raw_counts   : 800 counts",
            "  ambient_raw_counts: 700 counts",
            "Converted values",
            "  Temperatures (degC)",
            "    hot_temp_c        :",
            "    cold_temp_c       :",
            "    ambient_temp_c    :",
            "  Temperatures (degF)",
            "    hot_temp_f        :",
            "    cold_temp_f       :",
            "    ambient_temp_f    :",
            "  Flow",
            "    flow_gpm          :",
            " °C",
            " °F",
            " GPM",
        ):
            self.assertIn(report_text, output)

    def test_watch_prints_runtime_and_flow_raw_count_range(self) -> None:
        fake_reader = FakeReader(
            [
                self.make_snapshot(flow_raw_counts=810),
                self.make_snapshot(flow_raw_counts=790),
            ]
        )
        captured_output = io.StringIO()

        with (
            patch.object(
                sensor_check.time,
                "monotonic",
                side_effect=[100.0, 100.5, 102.0],
            ),
            patch.object(sensor_check.time, "sleep", return_value=None),
            contextlib.redirect_stdout(captured_output),
        ):
            with self.assertRaises(KeyboardInterrupt):
                sensor_check.run_sensor_check(
                    fake_reader,
                    watch=True,
                    interval_s=1.0,
                )

        self.assertEqual(fake_reader.get_sensor_snapshot_calls, 2)

        output = captured_output.getvalue()
        for report_text in (
            "Watch runtime",
            "  elapsed_s             : 2.0 s",
            "  snapshots             : 2",
            "  flow_raw_counts_min   : 790 counts",
            "  flow_raw_counts_max   : 810 counts",
        ):
            self.assertIn(report_text, output)


if __name__ == "__main__":
    unittest.main()
