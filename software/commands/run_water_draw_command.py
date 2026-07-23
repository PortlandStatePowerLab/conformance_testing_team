"""Command-line entrypoint for one controlled WH1 water draw."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from software.adc.max1238_builder import build_max1238
from software.runtime.controlled_water_draw_workflow import (
    MAX_RUN_MINUTES,
    run_controlled_water_draw,
)
from software.sensors.sensor_reader import SensorReader
from software.valve.gpio_valve_builder import build_gpio_valve


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one controlled WH1 water draw")
    parser.add_argument("--target-gal", type=float, required=True)
    parser.add_argument("--max-run-minutes", type=float, default=MAX_RUN_MINUTES)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.target_gal <= 0.0:
        raise SystemExit("--target-gal must be greater than zero")
    if args.max_run_minutes <= 0.0:
        raise SystemExit("--max-run-minutes must be greater than zero")

    adc = build_max1238()
    valve = None
    workflow_error: BaseException | None = None
    try:
        valve = build_gpio_valve()
        run_controlled_water_draw(
            args.target_gal,
            sensor_reader=SensorReader(adc),
            valve=valve,
            max_run_minutes=args.max_run_minutes,
        )
    except BaseException as error:
        workflow_error = error
        raise
    finally:
        cleanup_error = workflow_error
        try:
            if valve is not None:
                valve.cleanup()
        except BaseException as valve_cleanup_error:
            if cleanup_error is None:
                cleanup_error = valve_cleanup_error
            else:
                cleanup_error.add_note(
                    f"Valve cleanup also failed: {valve_cleanup_error!r}"
                )

        try:
            adc.close()
        except BaseException as adc_close_error:
            if cleanup_error is None:
                cleanup_error = adc_close_error
            else:
                cleanup_error.add_note(
                    f"ADC close also failed: {adc_close_error!r}"
                )

        if workflow_error is None and cleanup_error is not None:
            raise cleanup_error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
