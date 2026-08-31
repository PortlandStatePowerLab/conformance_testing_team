# Sensors

## Purpose

WH station sensor configuration, deterministic conversions, grouped measurement reading, and sensor diagnostics.

## Contains

- `__init__.py`: supported package exports: `SensorReader` and `SensorSnapshot`.
- `sensor_conversion_math.py`: deterministic signal and unit conversions.
- `sensor_configuration_loader.py`: optional configuration override loading and validation.
- `sensor_reader.py`: grouped ADC measurements and `SensorSnapshot`.
- `sensor_diagnostic.py`: reusable sensor reporting check.

## Public API

Supported consumers import the sensor reaer and snapshot through the package:

```python
from software.sensors import SensorReader, SensorSnapshot
```

Conversion math, configuration loading, channel assignments, diagnostics, and legacy sensor
helpers are not part of the supported sub-package API.

## Does not belong here

- ADC construction, GPIO control, or command-line parsing.

## Role rules

A reader retrieves and processes measurements; conversion math has no hardware access; a configuration loader reads validated overrides.

## Usage

insert something <- here

## Safety notes

Conversion and configuration modules are laptop-safe. The reader and diagnostic access hardware only through injected ADC objects.
