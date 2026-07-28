"""Laptop-safe tests for the controlled water-draw workflow."""

import unittest
from software.sensors.sensor_reader import SensorSnapshot

from software.runtime.controlled_water_draw_workflow import run_controlled_water_draw


class FakeValve:
    """Record physical valve commands and inject representative failures."""

    def __init__(
        self,
        *,
        open_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        """Initialize command counts and optional open or close failures."""
        self.open_count = 0
        self.close_count = 0
        self._open_error = open_error
        self._close_error = close_error

    def open(self) -> None:
        """Record an open command and optionally raise its configured error."""
        self.open_count += 1
        if self._open_error is not None:
            raise self._open_error

    def close(self) -> None:
        """Record a close command and optionally raise its configured error."""
        self.close_count += 1
        if self._close_error is not None:
            raise self._close_error


class FakeReader:
    def __init__(self, *, flow_gpm: float = 60.0, error: Exception | None = None) -> None:
        self._flow_gpm = flow_gpm
        self._error = error

    def get_sensor_snapshot(self) -> SensorSnapshot:
        if self._error is not None:
            raise self._error

        return SensorSnapshot(
            hot_raw_counts=0,
            cold_raw_counts=0,
            flow_raw_counts=0,
            ambient_raw_counts=0,
            hot_temp_c=40.0,
            hot_temp_f=104.0,
            cold_temp_c=20.0,
            cold_temp_f=68.0,
            ambient_temp_c=22.0,
            ambient_temp_f=71.6,
            flow_gpm=self._flow_gpm,
        )


class ControlledWaterDrawWorkflowTest(unittest.TestCase):
    def test_closes_valve_after_reaching_target(self) -> None:
        valve = FakeValve()
        times = iter((0.0, 1.0))

        volume = run_controlled_water_draw(
            1.0,
            sensor_reader=FakeReader(),
            valve=valve,
            monotonic=lambda: next(times),
            sleep=lambda _: None,
        )

        self.assertEqual(volume, 1.0)
        self.assertEqual(valve.open_count, 1)
        self.assertEqual(valve.close_count, 1)

    def test_closes_valve_when_sensor_read_raises(self) -> None:
        valve = FakeValve()
        times = iter((0.0, 0.1))

        with self.assertRaisesRegex(RuntimeError, "read failed"):
            run_controlled_water_draw(
                1.0,
                sensor_reader=FakeReader(error=RuntimeError("read failed")),
                valve=valve,
                monotonic=lambda: next(times),
                sleep=lambda _: None,
            )

        self.assertEqual(valve.open_count, 1)
        self.assertEqual(valve.close_count, 1)

    def test_closes_valve_when_open_raises(self) -> None:
        """A failed open command still triggers exactly one close attempt."""
        valve = FakeValve(open_error=RuntimeError("open failed"))

        with self.assertRaisesRegex(RuntimeError, "open failed"):
            run_controlled_water_draw(
                1.0,
                sensor_reader=FakeReader(),
                valve=valve,
            )

        self.assertEqual(valve.open_count, 1)
        self.assertEqual(valve.close_count, 1)

    def test_sensor_error_survives_valve_close_failure(self) -> None:
        """Preserve the sensor error and record a later physical close failure."""
        sensor_error = RuntimeError("read failed")
        close_error = RuntimeError("close failed")
        valve = FakeValve(close_error=close_error)
        times = iter((0.0, 0.1))

        with self.assertRaises(RuntimeError) as raised:
            run_controlled_water_draw(
                1.0,
                sensor_reader=FakeReader(error=sensor_error),
                valve=valve,
                monotonic=lambda: next(times),
                sleep=lambda _: None,
            )

        self.assertIs(raised.exception, sensor_error)
        self.assertEqual(
            sensor_error.__notes__,
            [f"Valve close also failed: {close_error!r}"],
        )
        self.assertEqual(valve.close_count, 1)


if __name__ == "__main__":
    unittest.main()
