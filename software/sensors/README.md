# Sensors

## Purpose

WH1 sensor configuration, deterministic conversions, grouped measurement reading, and sensor diagnostics.

## Contains

- `sensor_conversion_math.py`: deterministic signal and unit conversions.
- `sensor_configuration_loader.py`: calibration override loading and validation.
- `sensor_reader.py`: grouped ADC measurements and `SensorSnapshot`.
- `sensor_diagnostic.py`: reusable sensor reporting check.

## Does not belong here

- ADC construction, GPIO control, or command-line parsing.

## Role rules

A reader retrieves and processes measurements; conversion math has no hardware access; a configuration loader reads validated overrides.

## Usage

Import through `software.sensors.*`; operators run `bin/sensor-check`.

## Safety notes

Conversion and configuration modules are laptop-safe. The reader and diagnostic access hardware only through injected ADC objects.
