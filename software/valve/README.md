# Valve

## Purpose

WH Station valve requirements, direct GPIO control, safe construction, and diagnostic behavior.

## Contains

- `__init__.py`: supported package exports: `Valve` and `build_gpio_valve`.
- `valve_interface.py`: portable `Valve` control protocol.
- `gpio_valve_driver.py`: private Raspberry Pi GPIO relay control/driver.
- `gpio_valve_builder.py`: public, safe LOW-first valve construction boundary.
- `valve_diagnostic.py`: private controlled valve pulse and close-only diagnostic behavior checks.

## Public API

Supported consumers import the valve protocol and configured GPIO builder:

```python
from software.valve import Valve, build_gpio_valve
```

The GPIO driver, pin selection, station mapping, and diagnostic helpers are private
implementation details.

## Does not belong here

- Water-volume integration or CLI parsing.

## Role rules

An interface defines operations; a driver touches GPIO; a builder configures hardware; a diagnostic verifies behavior.

## Usage

Workflows depend on the `Valve` protocol. Hardware composition and operator commands construct
the installed valve through `build_gpio_valve()`. Human operators normally run `bin/valve-check`
for diagnostic behaviors.

## Safety notes

The builder and driver actuate GPIO17 and the connected valve. `bin/valve-check`
defaults to a 0.25-second open pulse; use `--state off` for a close-only command.

Importing `Valve` or `build_gpio_valve` is safe on Windows because `RPi.GPIO` is loaded
only when the builder is called. The caller owns the returned driver and must call `cleanup()`
when valve control is finished.
