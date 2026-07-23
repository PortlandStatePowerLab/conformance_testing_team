"""Command-line entrypoint for MAX1238 acquisition comparison."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from software.adc import adc_acquisition_diagnostic as diagnostic
from software.adc.adc_acquisition_diagnostic import (
    DEFAULT_CLOCK_MODE,
    DEFAULT_DELAY_S,
    DEFAULT_SAMPLES,
    DiagnosticAdc,
    run_comparison,
)
from software.adc.max1238_builder import (
    MAX1238_INTERNAL_REFERENCE_WAKEUP_S,
    build_max1238,
)

CH_HOT = diagnostic.CH_HOT
CH_COLD = diagnostic.CH_COLD
CH_FLOW = diagnostic.CH_FLOW
CH_AMBIENT = diagnostic.CH_AMBIENT
time = diagnostic.time


def positive_integer(value: str) -> int:
    parsed_value = int(value)
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed_value


def nonnegative_float(value: str) -> float:
    parsed_value = float(value)
    if parsed_value < 0.0 or not parsed_value < float("inf"):
        raise argparse.ArgumentTypeError("must be a nonnegative finite number")
    return parsed_value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare grouped and single MAX1238 reads.")
    parser.add_argument("--samples", type=positive_integer, default=DEFAULT_SAMPLES)
    parser.add_argument("--delay-s", type=nonnegative_float, default=DEFAULT_DELAY_S)
    parser.add_argument("--clock-mode", choices=("internal", "external"), default=DEFAULT_CLOCK_MODE)
    parser.add_argument("--watch", action="store_true")
    return parser.parse_args(argv)


def configure_clock_mode(adc: DiagnosticAdc, clock_mode: str) -> None:
    from software.adc.max1238_driver import ClockType, Polarity, ReferenceVoltage, ResetMode

    selected_clock = ClockType.Internal if clock_mode == "internal" else ClockType.External
    adc.setup_adc(
        referenceVoltage=ReferenceVoltage.InternalRef_AlwaysON_AnalogIn,
        clock=selected_clock,
        polarity=Polarity.Unipolar,
        reset=ResetMode.NoAction,
    )
    time.sleep(MAX1238_INTERNAL_REFERENCE_WAKEUP_S)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    adc = build_max1238()
    try:
        configure_clock_mode(adc, args.clock_mode)
        print(f"Selected clock mode: {args.clock_mode}")
        print("Only one hardware-owning process should run at a time.")
        run_comparison(adc, samples=args.samples, delay_s=args.delay_s, watch=args.watch)
    except KeyboardInterrupt:
        print("ADC acquisition comparison stopped.")
    finally:
        adc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
