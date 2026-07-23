"""Command-line entrypoint for the WH1 valve diagnostic."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from software.valve.gpio_valve_builder import build_gpio_valve
from software.valve.valve_diagnostic import MAX_PULSE_SECONDS, run_valve_diagnostic


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the WH1 valve relay path.")
    parser.add_argument("--state", choices=("off", "on"), default="on")
    parser.add_argument("--pulse-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    if not 0.0 <= args.pulse_seconds <= MAX_PULSE_SECONDS:
        parser.error("--pulse-seconds must be between 0 and 5 seconds")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    valve = build_gpio_valve()
    diagnostic_error: BaseException | None = None
    try:
        run_valve_diagnostic(
            valve=valve,
            requested_state=args.state,
            pulse_seconds=args.pulse_seconds,
        )
    except BaseException as error:
        diagnostic_error = error
        raise
    finally:
        if valve is not None:
            try:
                valve.cleanup()
            except BaseException as cleanup_error:
                if diagnostic_error is None:
                    raise
                diagnostic_error.add_note(
                    f"Valve cleanup also failed: {cleanup_error!r}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
