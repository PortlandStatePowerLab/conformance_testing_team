# Automated tests

## Purpose

Laptop-safe automated verification of package API's, hardware boundaries, commands, workflows,
data processing, reports, and plotting behavior.

## Contains

- `test_package_api.py`: exact public exports, multiple package import orders, and
    hardware-safe imports in isolated Python processes.
- `test_*_builder.py`: hardware-builder configuration, ownership, and cleanup behavior using
    injected (fake) or patched hardware modules.
- `test_*_command.py`: command parsing, dependency construction, workflow delegation,
    cleanup order, and error preservation.
- `test_*_workflow.py`: finite runtime behavior using injected (fake) readers, valves,
    clocks, and delay functions.
- Plotting and reporting tests: generated summaries, figures, timelines, and report
    content without live station hardware.
- Schedule tests: parsing, validation, compilation, GUI behavior, and workbook import.

## Does not belong here

- Manual station inspection procedures.
- Tests that unexpectedly access I2C, GPIO, relays, valves, or mains-connected equipment.
- Operator commands that print live diagnostic results.
- Hardware setup instructions or station commissioning checklists.

## Role rules

- Tests must be deterministic and independently runnable.
- Hardware access must be replaced with fakes, mocks, injected dependencies, or patched modules.
- Tests of supported consumer behavior should import through the package APIs.
- Tests may import private modules when directly verifying that implementation.
- APIimport-safety tests must run in isolated Python processes so existing `sys.modules` entries
    cannot hide eager imports, or circular dependencies.
- Cleanup and safety behavior must be tested when hardware operations or sensor reads fail.

## Usage

Run the complete test suite from the repository root:

```bash
python -m unittest discover -v
```

Run only the package API tests:

```bash
python -m unittest tests.test_package_api -v
```

Run one test module by its dotted module name:

```bash
python -m unittest tests.test_example_test_module.py
```

## Safety Notes

Automated tests must not actuate live station hardware. Builder and driver tests supply
fake ADC, SMBus, or GPIO dependencies instead of opening physical buses or changing GPIO
outputs.

Importing the public ADC, sensors, valve, and runtime packages must not load `smbus2`,
`RPi.GPIO`, or the MAX1238 hardware driver.

Plotting tests require `matplotlib`. When it is unavailable, those test modules fail during
import; that dependency failure is separate from the hardware-safe package API tests.
