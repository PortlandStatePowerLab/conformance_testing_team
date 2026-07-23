# Station

## Purpose

Station-wide physical assignments shared by multiple WH1 subsystems.

## Contains

- `station_hardware_map.py`: I2C addresses, ADC channels, GPIO assignments, and installed part identities.

## Does not belong here

- Hardware drivers, conversion math, or command-line code.

## Role rules

A hardware map names installed connections; it does not access hardware.

## Usage

Import from `software.station.station_hardware_map`. This module is safe to import on a non-Pi computer.
