"""Tests for the Windows-safe MAX1238 construction boundary."""

from __future__ import annotations

import sys
import types
import unittest
from enum import Enum
from unittest.mock import patch

from software.adc import max1238_builder


class FakeMax1238:
    """Record construction, setup, and cleanup without Pi hardware."""

    instances: list[FakeMax1238] = []
    setup_error: BaseException | None = None
    close_error: BaseException | None = None

    def __init__(self, *, address: int, bus_num: int) -> None:
        self.address = address
        self.bus_num = bus_num
        self.setup_calls: list[dict[str, object]] = []
        self.close_calls = 0
        self.instances.append(self)

    def setup_adc(self, **kwargs: object) -> None:
        """Record setup fields and optionally raise a representative failure."""
        self.setup_calls.append(kwargs)
        if self.setup_error is not None:
            raise self.setup_error

    def close(self) -> None:
        """Record closure and optionally simulate cleanup failure."""
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


def make_fake_driver_module() -> types.ModuleType:
    """Create the concrete-driver symbols without importing smbus2."""
    module = types.ModuleType("software.adc.max1238_driver")
    for enum_name, member_names in {
        "ClockType": ("Internal", "External"),
        "Polarity": ("Unipolar",),
        "ReferenceVoltage": ("InternalRef_AlwaysON_AnalogIn",),
        "ResetMode": ("NoAction",),
    }.items():
        setattr(module, enum_name, Enum(enum_name, member_names))
    module.Max1238 = FakeMax1238
    return module


class Max1238BuilderTest(unittest.TestCase):
    """Verify explicit configuration, timing, ownership, and cleanup."""

    def setUp(self) -> None:
        FakeMax1238.instances = []
        FakeMax1238.setup_error = None
        FakeMax1238.close_error = None

    def test_build_configures_external_clock_waits_and_returns_same_adc(self) -> None:
        """Return the configured object after the internal-reference wake-up."""
        fake_driver = make_fake_driver_module()
        events: list[tuple[str, object]] = []
        original_setup = FakeMax1238.setup_adc

        def record_setup(adc: FakeMax1238, **kwargs: object) -> None:
            events.append(("setup", kwargs))
            original_setup(adc, **kwargs)

        with (
            patch.dict(sys.modules, {"software.adc.max1238_driver": fake_driver}),
            patch.object(FakeMax1238, "setup_adc", record_setup),
            patch.object(
                max1238_builder.time,
                "sleep",
                side_effect=lambda delay: events.append(("sleep", delay)),
            ),
        ):
            adc = max1238_builder.build_max1238(bus_num=4, address=0x36)

        self.assertIs(adc, FakeMax1238.instances[0])
        self.assertEqual((adc.bus_num, adc.address), (4, 0x36))
        self.assertEqual(adc.close_calls, 0)
        setup = adc.setup_calls[0]
        self.assertEqual(
            setup["referenceVoltage"],
            fake_driver.ReferenceVoltage.InternalRef_AlwaysON_AnalogIn,
        )
        self.assertEqual(setup["clock"], fake_driver.ClockType.External)
        self.assertEqual(setup["polarity"], fake_driver.Polarity.Unipolar)
        self.assertEqual(setup["reset"], fake_driver.ResetMode.NoAction)
        self.assertEqual(events[0][0], "setup")
        self.assertEqual(
            events[1],
            ("sleep", max1238_builder.MAX1238_INTERNAL_REFERENCE_WAKEUP_S),
        )
    def test_build_closes_adc_and_reraises_setup_failure(self) -> None:
        """Close a constructed ADC when its explicit setup fails."""
        fake_driver = make_fake_driver_module()
        setup_error = OSError("fake setup failure")
        FakeMax1238.setup_error = setup_error

        with (
            patch.dict(sys.modules, {"software.adc.max1238_driver": fake_driver}),
            patch.object(max1238_builder.time, "sleep") as sleep,
        ):
            with self.assertRaises(OSError) as raised:
                max1238_builder.build_max1238()

        self.assertIs(raised.exception, setup_error)
        self.assertEqual(FakeMax1238.instances[0].close_calls, 1)
        sleep.assert_not_called()

    def test_cleanup_failure_does_not_mask_setup_failure(self) -> None:
        """Preserve the original setup error if close also fails."""
        fake_driver = make_fake_driver_module()
        setup_error = OSError("fake setup failure")
        FakeMax1238.setup_error = setup_error
        FakeMax1238.close_error = RuntimeError("fake close failure")

        with patch.dict(sys.modules, {"software.adc.max1238_driver": fake_driver}):
            with self.assertRaises(OSError) as raised:
                max1238_builder.build_max1238()

        self.assertIs(raised.exception, setup_error)
        self.assertEqual(FakeMax1238.instances[0].close_calls, 1)


if __name__ == "__main__":
    unittest.main()
