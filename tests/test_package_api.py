"""Tests for API cross-package, circular, and hardware-safe imports, as well as public
package exports and import orders.

These tests protect the supported package front doors without constructing "real" ADC or
GPIO hardware. Fresh Python subproccesses prevent earlier test imports from hiding eager-import
problems through ``sys.modules`` caching
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path

# Repository root used as the working directory for isolated Python processes
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Exact supported exports for each public subpackage
PUBLIC_EXPORTS: dict[str, tuple[str, ...]] = {
    "software.adc": ("SensorAdc", "build_max1238"),
    "software.sensors": ("SensorReader", "SensorSnapshot"),
    "software.valve": ("Valve", "build_gpio_valve"),
    "software.runtime": ("run_controlled_water_draw",),
}

# Each public package is imported first in at least one fresh interpreter
IMPORT_ORDERS: tuple[tuple[str, ...], ...] = (
    (
        "software.adc",
        "software.sensors",
        "software.valve",
        "software.runtime",
    ),
    (
        "software.sensors",
        "software.runtime",
        "software.adc",
        "software.valve",
    ),
    (
        "software.valve",
        "software.runtime",
        "software.sensors",
        "software.adc",
    ),
    (
        "software.runtime",
        "software.valve",
        "software.sensors",
        "software.adc",
    ),
)

def _run_isolated_python(script: str) -> subprocess.CompletedProcess[str]:
    """Run one Python script in an isolated interpreter from the repository root.

    Args:
        script (str): Python source passed to the isolated interpreter.

    Returns:
        Completed process containing the exit code, standard output, and standard error
        produced by the isolated interpreter.

    Safety:
        The subprocess imports software only. It does not invoke hardware builders,
        open I2C buses, configure GPIO, or actuate the valve.
    """
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )


class PackageApiTest(unittest.TestCase):
    """Protect the supported package APIs and their import boundaries."""

    def test_public_exports_are_exact(self)->None:
        """Each public subpackage should expose only its supported API names."""
        for package_name, expected_exports in PUBLIC_EXPORTS.items():
            with self.subTest(package=package_name):
                package = importlib.import_module(package_name)
                actual_exports = tuple(package.__all__)

                self.assertEqual(actual_exports, expected_exports)

                # Confirm every declared export is actually available through the
                # package "front door".
                for export_name in expected_exports:
                    self.assertTrue(
                        hasattr(package, export_name),
                        f"{package_name} does not expose {export_name}",
                    )

    def test_public_api_packages_import_without_hardware_dependencies(self)->None:
        """Public importsmust not eagerly load Pi-only hardware libraries."""
        script = """
import sys

from software.adc import SensorAdc, build_max1238
from software.runtime import run_controlled_water_draw
from software.sensors import SensorReader, SensorSnapshot
from software.valve import Valve, build_gpio_valve

assert SensorAdc is not None
assert callable(build_max1238)
assert SensorReader is not None
assert SensorSnapshot is not None
assert Valve is not None
assert callable(build_gpio_valve)
assert callable(run_controlled_water_draw)

assert "software.adc.max1238_driver" not in sys.modules
assert "smbus2" not in sys.modules
assert "RPi" not in sys.modules
assert "RPi.GPIO" not in sys.modules
"""

        result = _run_isolated_python(script)

        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "Public package import loaded a hardware dependency or failed.\n"
                f"stdouit:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ),
        )

    def test_public_packages_import_in_multiple_orders(self)->None:
        """Public packages should not depend on one successful import order."""
        for import_order in IMPORT_ORDERS:
            with self.subTest(import_order=import_order):
                # A new interreter for every order ensures cached modules from a previous
                # order cannot conceal a circular dependency.
                script = "\n".join(
                    f"import {package_name}"
                    for package_name in import_order
                )
                result = _run_isolated_python(script)

                self.assertEqual(
                    result.returncode,
                    0,
                    msg=(
                        "Public package import order failed: "
                        f"{' -> '.join(import_order)}\n"
                        f"stdout:\n{result.stdout}\n"
                        f"stderr:\n{result.stderr}"
                    ),
                )

    def test_helpers_does_not_reexport_cold_water_socket_support(self) -> None:
        """The legacy helpers packagemust not expose cold-water internals."""
        helpers = importlib.import_module("software.helpers")

        self.assertFalse(hasattr(helpers, "_unix_socket_family"))


if __name__ == "__main__":
    unittest.main()
