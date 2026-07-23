"""Dry-run-first diagnostic behavior for the WH1 valve relay."""

from __future__ import annotations

import time
from collections.abc import Callable

from software.station.station_hardware_map import VALVE_PIN
from software.valve.valve_interface import Valve

MAX_PULSE_SECONDS = 5.0


def run_valve_diagnostic(
    *,
    valve: Valve,
    requested_state: str,
    pulse_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Exercise an injected valve and restore its physical closed state."""
    if requested_state not in {"off", "on"}:
        raise ValueError("requested_state must be 'off' or 'on'")
    if not 0.0 <= pulse_seconds <= MAX_PULSE_SECONDS:
        raise ValueError("pulse_seconds must be between 0 and 5 seconds")

    diagnostic_error: BaseException | None = None
    try:
        if requested_state == "on":
            valve.open()
            print(f"GPIO{VALVE_PIN} HIGH for {pulse_seconds:.2f} seconds")
            sleep(pulse_seconds)
        else:
            print(f"GPIO{VALVE_PIN} LOW requested")
    except BaseException as error:
        diagnostic_error = error
        raise
    finally:
        try:
            valve.close()
            print(f"GPIO{VALVE_PIN} LOW")
        except BaseException as close_error:
            if diagnostic_error is None:
                raise
            diagnostic_error.add_note(
                f"Valve close also failed: {close_error!r}"
            )
