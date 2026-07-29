"""Tests for the hardware-independent MAX1238 acquisition diagnostic."""

from __future__ import annotations

import contextlib
import io
import sys
import types
import unittest
from enum import Enum
from unittest.mock import patch

from software.commands import check_adc_acquisition_command as compare_adc_acquisition


class FakeAdc:
    """Record deterministic grouped and single reads without Pi hardware."""

    def __init__(self) -> None:
        """Initialize call history, values, and ownership state."""
        self.calls: list[tuple[object, ...]] = []
        self.single_values = iter((1042, 1082, 1100, 1104))
        self.closed = False
        self.setup_calls: list[dict[str, object]] = []

    def setup_adc(self, **kwargs: object) -> None:
        """Record explicit post-builder configuration."""
        self.setup_calls.append(kwargs)

    def read_single(self, channel: int, /) -> int:
        """Return the next deterministic single-read value."""
        self.calls.append(("read_single", channel))
        return next(self.single_values)

    def read_range(self, first_channel: int, last_channel: int, /) -> dict[int, int]:
        """Return a deliberately non-positional grouped channel mapping."""
        self.calls.append(("read_range", first_channel, last_channel))
        return {
            compare_adc_acquisition.CH_FLOW: 1002,
            compare_adc_acquisition.CH_HOT: 900,
            compare_adc_acquisition.CH_AMBIENT: 904,
            compare_adc_acquisition.CH_COLD: 901,
        }

    def close(self) -> None:
        """Record closure of the owned fake ADC."""
        self.closed = True


class RaisingFakeAdc(FakeAdc):
    """Raise during acquisition to verify ownership cleanup."""

    def read_range(self, first_channel: int, last_channel: int, /) -> dict[int, int]:
        """Raise a representative I2C read failure."""
        raise OSError("fake I2C failure")


class CompareAdcAcquisitionTest(unittest.TestCase):
    """Verify ordering, channel selection, deltas, and ADC ownership."""

    def test_main_uses_one_adc_for_all_sequences_and_closes(self) -> None:
        """Exercise A, B, and C on the single object returned by the builder."""
        fake_adc = FakeAdc()
        captured_output = io.StringIO()

        fake_driver = self.make_fake_driver_module()
        with (
            patch.object(
                compare_adc_acquisition, "build_max1238", return_value=fake_adc
            ) as build_max1238,
            patch.dict(sys.modules, {"software.adc.max1238_driver": fake_driver}),
            patch.object(compare_adc_acquisition.time, "sleep", return_value=None),
            contextlib.redirect_stdout(captured_output),
        ):
            exit_code = compare_adc_acquisition.main(["--samples", "3", "--delay-s", "0"])

        self.assertEqual(exit_code, 0)
        build_max1238.assert_called_once_with()
        self.assertTrue(fake_adc.closed)
        self.assertEqual(fake_adc.setup_calls[0]["clock"], fake_driver.ClockType.Internal)
        self.assertEqual(
            fake_adc.calls,
            [
                ("read_range", compare_adc_acquisition.CH_HOT, compare_adc_acquisition.CH_AMBIENT),
                ("read_single", compare_adc_acquisition.CH_FLOW),
                ("read_single", compare_adc_acquisition.CH_FLOW),
                ("read_range", compare_adc_acquisition.CH_HOT, compare_adc_acquisition.CH_AMBIENT),
                ("read_single", compare_adc_acquisition.CH_FLOW),
                ("read_single", compare_adc_acquisition.CH_FLOW),
            ],
        )
        self.assertNotIn("software.adc.max1238_driver", sys.modules)
        self.assertNotIn("smbus2", sys.modules)

        output = captured_output.getvalue()
        self.assertIn("sequence=A grouped_flow_counts=1002", output)
        self.assertIn("single_flow_counts=1042", output)
        self.assertIn("delta_counts=40", output)
        self.assertIn("sequence=B grouped_flow_counts=1002", output)
        self.assertIn("single_flow_counts=1082", output)
        self.assertIn("delta_counts=80", output)
        self.assertIn("sequence=C first_single_counts=1100", output)
        self.assertIn("second_single_counts=1104", output)
        self.assertIn("delta_counts=4", output)
        self.assertIn("Sequence A: sample_count=1", output)
        self.assertIn("grouped_minimum_counts=1002", output)
        self.assertIn("single_minimum_counts=1042", output)
        self.assertIn("delta_mean_counts=40.00", output)
        self.assertIn("first_single_minimum_counts=1100", output)
        self.assertIn("second_single_minimum_counts=1104", output)

    @staticmethod
    def make_fake_driver_module() -> types.ModuleType:
        """Return enum-only driver stand-ins without importing Linux hardware."""
        module = types.ModuleType("software.adc.max1238_driver")
        for enum_name, member_names in {
            "ClockType": ("Internal", "External"),
            "Polarity": ("Unipolar",),
            "ReferenceVoltage": ("InternalRef_AlwaysON_AnalogIn",),
            "ResetMode": ("NoAction",),
        }.items():
            setattr(module, enum_name, Enum(enum_name, member_names))
        return module

    def test_clock_modes_retain_setup_fields_and_wait_after_reconfiguration(self) -> None:
        """Select either clock while retaining reference, polarity, reset, and delay."""
        fake_driver = self.make_fake_driver_module()
        for mode, expected_clock in (
            ("internal", fake_driver.ClockType.Internal),
            ("external", fake_driver.ClockType.External),
        ):
            with self.subTest(mode=mode):
                fake_adc = FakeAdc()
                events: list[tuple[str, object]] = []
                fake_adc.setup_adc = lambda **kwargs: events.append(("setup", kwargs))
                with (
                    patch.dict(sys.modules, {"software.adc.max1238_driver": fake_driver}),
                    patch.object(
                        compare_adc_acquisition.time,
                        "sleep",
                        side_effect=lambda delay: events.append(("sleep", delay)),
                    ),
                ):
                    compare_adc_acquisition.configure_clock_mode(fake_adc, mode)
                setup = events[0][1]
                self.assertEqual(setup["clock"], expected_clock)
                self.assertEqual(
                    setup["referenceVoltage"],
                    fake_driver.ReferenceVoltage.InternalRef_AlwaysON_AnalogIn,
                )
                self.assertEqual(setup["polarity"], fake_driver.Polarity.Unipolar)
                self.assertEqual(setup["reset"], fake_driver.ResetMode.NoAction)
                self.assertEqual(
                    events[1],
                    ("sleep", compare_adc_acquisition.MAX1238_INTERNAL_REFERENCE_WAKEUP_S),
                )

    def test_main_closes_adc_after_acquisition_exception(self) -> None:
        """Close the owned ADC when an acquisition read raises."""
        fake_adc = RaisingFakeAdc()
        fake_driver = self.make_fake_driver_module()
        with (
            patch.object(compare_adc_acquisition, "build_max1238", return_value=fake_adc),
            patch.dict(sys.modules, {"software.adc.max1238_driver": fake_driver}),
            patch.object(compare_adc_acquisition.time, "sleep", return_value=None),
        ):
            with self.assertRaisesRegex(OSError, "fake I2C failure"):
                compare_adc_acquisition.main(["--samples", "1", "--delay-s", "0"])
        self.assertTrue(fake_adc.closed)

    def test_cli_validates_samples_and_delay(self) -> None:
        """Reject nonpositive sample counts and negative delays."""
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                compare_adc_acquisition.parse_args(["--samples", "0"])
            with self.assertRaises(SystemExit):
                compare_adc_acquisition.parse_args(["--delay-s", "-0.1"])
        self.assertEqual(
            compare_adc_acquisition.parse_args([]).clock_mode, "internal"
        )


if __name__ == "__main__":
    unittest.main()
