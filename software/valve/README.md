# Valve

## Purpose

WH1 valve requirements, direct GPIO control, safe construction, and diagnostic behavior.

## Contains

- `valve_interface.py`: operations required by workflows.
- `gpio_valve_driver.py`: direct GPIO relay control.
- `gpio_valve_builder.py`: safe LOW-first driver construction.
- `valve_diagnostic.py`: controlled valve pulse and close-only check behavior.

## Does not belong here

- Water-volume integration or CLI parsing.

## Role rules

An interface defines operations; a driver touches GPIO; a builder configures hardware; a diagnostic verifies behavior.

## Usage

Import the interface in workflows. Operators run `bin/valve-check`.

## Safety notes

The builder and driver actuate GPIO17 and the connected valve. `bin/valve-check`
defaults to a 0.25-second open pulse; use `--state off` for a close-only command.
