"""Finite, dependency-injected WH1 controlled water-draw workflow."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from software.sensors.sensor_reader import SensorSnapshot
from software.valve.valve_interface import Valve

MAX_RUN_MINUTES = 5.0
MIN_FLOW_GPM = 0.05
LOW_FLOW_TIMEOUT_S = 20.0
PRINT_PERIOD_S = 0.5


class SensorSnapshotReader(Protocol):
    """Define the grouped sensor-read operation required by the draw workflow"""

    def get_sensor_snapshot(self) -> SensorSnapshot:
        """Return one grouped temperature and flow snapshot"""
        ...


def run_controlled_water_draw(
    target_volume_gal: float,
    *,
    sensor_reader: SensorSnapshotReader,
    valve: Valve,
    max_run_minutes: float = MAX_RUN_MINUTES,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    """Open the valve, integrate measured flow, and close at the target."""
    if target_volume_gal <= 0.0:
        raise ValueError("target volume must be greater than 0 gallons")
    if max_run_minutes <= 0.0:
        raise ValueError("maximum run time must be greater than 0 minutes")

    print(f"Target: {target_volume_gal:.3f} gal")
    volume_gal = 0.0
    start = monotonic()
    previous = start
    last_log = start
    low_flow_start: float | None = None

    workflow_error: BaseException | None = None
    try:
        valve.open()
        print("Valve command asserted")

        while volume_gal < target_volume_gal:
            now = monotonic()
            elapsed_s = now - start
            delta_s = now - previous
            previous = now

            if elapsed_s > max_run_minutes * 60.0:
                print("[!] Timeout reached. Stopping.")
                break

            snapshot = sensor_reader.get_sensor_snapshot()
            values = (
                snapshot.hot_temp_c,
                snapshot.cold_temp_c,
                snapshot.ambient_temp_c,
                snapshot.flow_gpm,
            )
            if any(value != value for value in values):
                print("[!] Sensor read error. Stopping.")
                break

            volume_gal += max(snapshot.flow_gpm, 0.0) * (delta_s / 60.0)

            if snapshot.flow_gpm < MIN_FLOW_GPM:
                if low_flow_start is None:
                    low_flow_start = now
                elif now - low_flow_start >= LOW_FLOW_TIMEOUT_S:
                    print("[!] Low flow persisted. Stopping.")
                    break
            else:
                low_flow_start = None

            if now - last_log >= PRINT_PERIOD_S:
                print(
                    f"T_hot={snapshot.hot_temp_c:.1f} C  "
                    f"T_cold={snapshot.cold_temp_c:.1f} C  "
                    f"T_ambient={snapshot.ambient_temp_c:.1f} C  "
                    f"Flow={snapshot.flow_gpm:.2f} gpm  "
                    f"Volume={volume_gal:.3f} gal"
                )
                last_log = now

            sleep(0.05)
    except BaseException as error:
        workflow_error = error
        raise
    finally:
        try:
            valve.close()
            print("Valve command cleared")
        except BaseException as close_error:
            if workflow_error is None:
                raise
            workflow_error.add_note(
                f"Valve close also failed: {close_error!r}"
            )

    print(f"Volume drawn: {volume_gal:.3f} gal")
    return volume_gal
