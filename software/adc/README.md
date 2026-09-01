# ADC

## Purpose

WH station MAX1238 communication, construction, interfaces, and read-only ADC diagnostics.

## Contains

- `__init__.py`: supported package exports: `SensorAdc` and `build_max1238`.
- `adc_acquisition_diagnostic.py`: private, reusable grouped-versus-single acquisition diagnostic logic.
- `adc_interfaces.py`: portable `SensorAdc` read protocol.
- `adc_raw_diagnostic.py`: private, reusable raw-channel diagnostic logic.
- `max1238_builder.py`: public, configured MAX1238 construction boundary.
- `max1238_driver.py`: private, direct MAX1238 I2C driver.

## Public API

Supported callers import only the portable protocol and configured device builder:

```python
from software.adc import SensorAdc, build_max1238
```

The hardware-specific `Max1238` class, the configuration decisions, start-up timing constant,
and the diagnostic helpers are private implementation details.

Station-specific I2C bus number and MAX1238 device address selection are wiring details
that belong in `software/station/station_adc_builder.py`

## Does not belong here

- Physical-station wiring choices, such as the installed I2C bus, device address, and
    sensor-channel assignments. Those belong in `software/station/`.
- Sensor conversion math, engineering units, calibration, and sensor configuration. Those
    belong in `software/sensors/`.
- Command-line argument parsing and operator entrypoints. Those belong in `software/commands/` and `bin/`.

## Role rules

- An interface describes the minimum ADC read operations that portable sensor code may request.
    It does not select or construct hardware.
- A driver communicates directly with one hardware model over I2C and owns its open bus connection.
- A device builder constructs and configures that driver using connection details supplied by its caller.
- A station builder supplies the bus number and device address from the station hardware map.
- A diagnostic exercises ADC behavior and reports results without becoming part of the supported package API.
- When a caller receives an ADC object from a builder, that caller owns the object, and must close it when finished.

## Usage

Portable sensor code should receive a `SensorAdc` object from its caller instead of constructing hardware.

Code that needs to construct a MAX1238 for a caller-selected I2C bus and address may import `build_max1238`
through the `software.adc` public API.

Normal selection processes should use `build_station_adc()` from `software/station/station_adc_builder.py`
so the installed bus number and device address come from the station hardware map.

Operators normally run the supported `bin/adc-raw` or `bin/adc-acquisition-compare` entrypoints
instead of importing diagnostic modules directly.

## Safety notes

Importing `SensorAdc` or `build_max1238` from `software.adc` is safe on Windows because the
Linux-only MAX1238 driver and `smbus2` dependency are loaded only when the builder is called.

Calling `build_max1238()` opens the selected I2C bus, constructs the physical ADC driver,
sends the MAX1238 setup configuration, and waits for the internal voltage reference to stabilize.
The caller owns the returned ADC object and must close it when finished.

If construction or setup fails, the builder will attempt to close any partially constructed
ADC object before allowing the failure to propagate.

Only one hardware-owning process should control a station ADC at a time unless access is
deliberately shared through the station service architecture.

The ADC builder and diagnostics access only the MAX1238 over I2C. They do not configure
GPIO, actuate the water valve, or communicate with the ACS37800 power monitor.
