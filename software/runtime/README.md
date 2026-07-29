# Runtime

## Purpose

Finite or ongoing station coordination that combines subsystem dependencies.

## Contains

- `controlled_water_draw_workflow.py`: one finite target-volume water draw.

## Does not belong here

- CLI parsing, direct GPIO imports, hardware construction, or conversion formulas.

## Role rules

A workflow is a finite multi-step lab procedure; runtime code coordinates subsystems without becoming their driver.

## Usage

Import the workflow through `software.runtime.controlled_water_draw_workflow`; operators run `bin/wh-draw`.

## Safety notes

The workflow can actuate an injected valve and consume live sensor readings. It must receive correctly configured dependencies and always closes the valve on exit.
