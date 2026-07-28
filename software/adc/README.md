# ADC

## Purpose

MAX1238 communication, construction, interfaces, and read-only ADC diagnostics.

## Contains

- `adc_interface.py`: required ADC read operations.
- `max1238_driver.py`: direct MAX1238 I2C driver.
- `max1238_builder.py`: configured station ADC construction.
- `adc_raw_diagnostic.py`, `adc_acquisition_diagnostic.py`: reusable read-only checks.

## Does not belong here

- Sensor engineering-unit conversion or CLI parsing.

## Role rules

A driver communicates over I2C; a builder configures it; an interface defines required reads; a diagnostic verifies behavior.

## Usage

Import these modules. Operators normally run `bin/adc-raw` or `bin/adc-acquisition-compare`.

## Safety notes

The driver, builder, and diagnostics access real I2C hardware on a Pi. The interface is laptop-safe; driver construction is not.
