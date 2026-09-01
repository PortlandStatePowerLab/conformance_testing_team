# Runtime

## Purpose

Manually invoked commissioning workflows that coordinate configured station
subsystems without owning their construction.

## Contains

- `__init__.py`: supported package export: `run_controlled_water_draw`.
- `controlled_water_draw_workflow.py`: one manual, finite target-volume water draw.

## Public API

Supported consumers import the controlled water-draw workflow through the package:

```python
from software.runtime import run_controlled_water_draw
```

Runtime limits, low-flow settings, reporting cadence, internal dependency protocols,
and workflow-loop details are not part of the supported package API.

## Does not belong here

- CLI parsing, direct GPIO imports, hardware construction, or conversion formulas.

## Role rules

A workflow is a finite multi-step lab procedure. Runtime code coordinates borrowed
subsystem dependencies without constructing them or becoming their hardware driver.

## Usage

Use `run_controlled_water_draw()` for a manually requested commissioning draw.
Operators normally invoke the workflow through `bin/wh-draw`.

Scheduled conformance-test water draws use `software.water_draw_monitor`; they do
not run through this manual commissioning workflow.

## Safety notes

The workflow actuates an injected valve and consumes live sensor readings. It must
receive correctly configured dependencies and always attempts to close the valve on
exit. The caller retains ownership of the valve and sensor session and must perform
final cleanup.
