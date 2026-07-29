"""Tests for the hardware-independent read-adc-raw diagnostic."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from software.commands import check_adc_raw_command as read_adc_raw


class FakeAdc:
    """Provide deterministic raw counts without importing Pi hardware."""

    def __init__(self) -> None:
        self.read_single_channels: list[int] = []
        self.closed = False

    def read_single(self, channel: int, /) -> int:
        self.read_single_channels.append(channel)
        return 1000 + channel

    def close(self) -> None:
        self.closed = True


class SequenceFakeAdc:
    """Provide deterministic raw-count scans for watch-mode tests."""

    def __init__(self, scans: list[dict[int, int]]) -> None:
        self._scans = scans
        self.read_single_channels: list[int] = []
        self.closed = False

    def read_single(self, channel: int, /) -> int:
        scan_index = len(self.read_single_channels) // len(read_adc_raw.CHANNELS)
        if scan_index >= len(self._scans):
            raise KeyboardInterrupt

        self.read_single_channels.append(channel)
        return self._scans[scan_index][channel]

    def close(self) -> None:
        self.closed = True


class ReadAdcRawTest(unittest.TestCase):
    """Verify one-shot raw ADC diagnostic assembly with a pure fake ADC."""

    def test_main_builds_once_prints_channel_report_and_closes(self) -> None:
        fake_adc = FakeAdc()
        captured_output = io.StringIO()

        with (
            patch.object(
                read_adc_raw,
                "build_max1238",
                return_value=fake_adc,
            ) as build_max1238,
            contextlib.redirect_stdout(captured_output),
        ):
            exit_code = read_adc_raw.main([])

        self.assertEqual(exit_code, 0)
        build_max1238.assert_called_once_with(
            bus_num=read_adc_raw.MAX1238_I2C_BUS,
            address=read_adc_raw.MAX1238_I2C_ADDR,
        )
        self.assertEqual(
            fake_adc.read_single_channels,
            [channel for _, channel in read_adc_raw.CHANNELS],
        )
        self.assertTrue(fake_adc.closed)
        self.assertNotIn("software.adc.max1238_driver", sys.modules)
        self.assertNotIn("smbus2", sys.modules)

        output = captured_output.getvalue()
        for report_text in (
            "ADC raw diagnostic at ",
            "ADC configuration",
            "  adc_part              :",
            f"  i2c_bus               : {read_adc_raw.MAX1238_I2C_BUS}",
            f"  i2c_address           : 0x{read_adc_raw.MAX1238_I2C_ADDR:02X}",
            "  reference_voltage_v   :",
            "Channel readings",
            "  CH",
            "    raw_counts        :",
            " counts",
            "    input_voltage_v   :",
            " V",
        ):
            self.assertIn(report_text, output)

    def test_watch_prints_runtime_and_channel_raw_count_ranges(self) -> None:
        first_scan = {
            channel: 1000 + channel
            for _label, channel in read_adc_raw.CHANNELS
        }
        second_scan = {
            channel: 900 + channel
            for _label, channel in read_adc_raw.CHANNELS
        }
        fake_adc = SequenceFakeAdc([first_scan, second_scan])
        captured_output = io.StringIO()

        with (
            patch.object(
                read_adc_raw,
                "build_max1238",
                return_value=fake_adc,
            ) as build_max1238,
            patch.object(
                read_adc_raw.time,
                "monotonic",
                side_effect=[100.0, 100.5, 102.0],
            ),
            patch.object(read_adc_raw.time, "sleep", return_value=None),
            contextlib.redirect_stdout(captured_output),
        ):
            exit_code = read_adc_raw.main(["--watch"])

        self.assertEqual(exit_code, 0)
        build_max1238.assert_called_once_with(
            bus_num=read_adc_raw.MAX1238_I2C_BUS,
            address=read_adc_raw.MAX1238_I2C_ADDR,
        )
        self.assertEqual(
            fake_adc.read_single_channels,
            [channel for _, channel in read_adc_raw.CHANNELS] * 2,
        )
        self.assertTrue(fake_adc.closed)

        output = captured_output.getvalue()
        for report_text in (
            "ADC raw watch runtime",
            "  elapsed_s             : 2.0 s",
            "  scans                 : 2",
            "Raw count ranges",
            "    min_raw_counts    : 900 counts",
            "    max_raw_counts    : 1000 counts",
            "ADC raw watch stopped.",
        ):
            self.assertIn(report_text, output)

        for label, channel in read_adc_raw.CHANNELS:
            self.assertIn(f"  CH{channel} {label}", output)


if __name__ == "__main__":
    unittest.main()
