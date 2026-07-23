# Commands

## Purpose

User-invoked Python entrypoints that parse arguments, construct dependencies, call diagnostics or workflows, and choose exit codes.

## Contains

- `run_water_draw_command.py`: controlled draw command.
- `check_*_command.py`: ADC, sensor, and valve checks.

## Does not belong here

- Reusable conversion math, hardware driver implementations, or workflow loops.

## Role rules

A command is a user-invoked Python entrypoint. It calls subsystem diagnostics or runtime workflows.

## Usage

Prefer the matching `bin/` command. Python module form is `python3 -m software.commands.<command_name>`.

## Safety notes

Some commands open I2C devices or actuate GPIO. Read `--help` before running a hardware command.
